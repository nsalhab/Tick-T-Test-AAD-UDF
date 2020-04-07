from kapacitor.udf.agent import Agent, Handler
from scipy import stats
import math
import kapacitor.udf.udf_pb2
import sys


# The Agent calls the appropriate methods on the Handler as requests are read off STDIN.
#
# Throwing an exception will cause the Agent to stop and an ErrorResponse to be sent.
# Some *Response objects (like SnapshotResponse) allow for returning their own error within the object itself.
# These types of errors will not stop the Agent and Kapacitor will deal with them appropriately.
#
# The Handler is called from a single thread, meaning methods will not be called concurrently.
#
# To write Points/Batches back to the Agent/Kapacitor use the Agent.write_response method, which is thread safe.

class TtestHandler(Handler):
    """
    Keep a rolling window of historically normal data
    When a new window arrives use a two-sided t-test to determine
    if the new window is statistically significantly different.
    """
    def __init__(self, agent):
        self._agent = agent

        self._field = ''
        self._history = None

        self._batch = None

        self._alpha = 0.0


# Let’s start with the info method. When Kapacitor starts up it will call info and expect in return some information about how this UDF behaves. Specifically, Kapacitor expects the kind of edge the UDF wants and provides.
# In addition, UDFs can accept certain options so that they are individually configurable. The info response can contain a list of options, their names, and expected arguments.

# 	For our example UDF, we need to know three things:
#    	The field to operate on.
#    	The size of the historical window to keep.
#    	The significance level or alpha being used.

# When Kapacitor starts, it will spawn our UDF process and request the info data and then shutdown the process. Kapacitor will remember this information for each UDF. This way, Kapacitor can understand the available options for a given UDF before its executed inside of a task.

    def info(self):
        """
        Respond with which type of edges we want/provide and any options we have.
        """
        response = udf_pb2.Response()
        # We will consume batch edges aka windows of data.
        response.info.wants = udf_pb2.BATCH
        # We will produce single points of data aka stream.
        response.info.provides = udf_pb2.STREAM

        # Here we can define options for the UDF.
        # Define which field we should process
        response.info.options['field'].valueTypes.append(udf_pb2.STRING)

        # Since we will be computing a moving average let's make the size configurable.
        # Define an option 'size' that takes one integer argument.
        response.info.options['size'].valueTypes.append(udf_pb2.INT)

        # We need to know the alpha level so that we can ignore bad windows
        # Define an option 'alpha' that takes one double argument.
        response.info.options['alpha'].valueTypes.append(udf_pb2.DOUBLE)

        return response

# Next let’s implement the init method, which is called once the task starts executing. The init method receives a list of chosen options, which are then used to configure the handler appropriately. In response, we indicate whether the init request was successful, and, if not, any error messages if the options were invalid.
# When a task starts, Kapacitor spawns a new process for the UDF and calls init, passing any specified options from the TICKscript. Once initialized, the process will remain running and Kapacitor will begin sending data as it arrives.

    def init(self, init_req):
        """
        Given a list of options initialize this instance of the handler
        """
        success = True
        msg = ''
        size = 0
        for opt in init_req.options:
            if opt.name == 'field':
                self._field = opt.values[0].stringValue
            elif opt.name == 'size':
                size = opt.values[0].intValue
            elif opt.name == 'alpha':
                self._alpha = opt.values[0].doubleValue

        if size <= 1:
            success = False
            msg += ' must supply window size > 1'
        if self._field == '':
            success = False
            msg += ' must supply a field name'
        if self._alpha == 0:
            success = False
            msg += ' must supply an alpha value'

        # Initialize our historical window
        self._history = MovingStats(size)

        response = udf_pb2.Response()
        response.init.success = success
        response.init.error = msg[1:]

        return response

# Our task wants a batch edge, meaning it expects to get data in batches or windows. To send a batch of data to the UDF process, Kapacitor first calls the begin_batch method, which indicates that all subsequent points belong to a batch. Once the batch is complete, the end_batch method is called with some metadata about the batch.

# At a high level, this is what our UDF code will do for each of the begin_batch, point, and end_batch calls:

#    begin_batch: mark the start of a new batch and initialize a structure for it
#    point: store the point
#    end_batch: perform the t-test and then update the historical data


    def begin_batch(self, begin_req):
        # create new window for batch
        self._batch = MovingStats(-1)

    def point(self, point):
        self._batch.update(point.fieldsDouble[self._field])

    def end_batch(self, batch_meta):
        pvalue = 1.0
        if self._history.n != 0:
            # Perform Welch's t test
            t, pvalue = stats.ttest_ind_from_stats(
                    self._history.mean, self._history.stddev(), self._history.n,
                    self._batch.mean, self._batch.stddev(), self._batch.n,
                    equal_var=False)


            # Send pvalue point back to Kapacitor
            response = udf_pb2.Response()
            response.point.time = batch_meta.tmax
            response.point.name = batch_meta.name
            response.point.group = batch_meta.group
            response.point.tags.update(batch_meta.tags)
            response.point.fieldsDouble["t"] = t
            response.point.fieldsDouble["pvalue"] = pvalue
            self._agent.write_response(response)

        # Update historical stats with batch, but only if it was normal.
        if pvalue > self._alpha:
            for value in self._batch._window:
                self._history.update(value)


class MovingStats(object):
    """
    Calculate the moving mean and variance of a window.
    Uses Welford's Algorithm.
    """
	# Welford's algorithm allows to compute the variance in a single pass, 
	# inspecting each value x_i only once; 
	# this is interesting, when the data are being collected without enough storage to keep all the values, 
	# or when costs of memory access dominate those of computation.
    def __init__(self, size):
        """
        Create new MovingStats object.
        Size can be -1, infinite size or > 1 meaning static size
        """
        self.size = size
        if not (self.size == -1 or self.size > 1):
            raise Exception("size must be -1 or > 1")


        self._window = []
        self.n = 0.0
        self.mean = 0.0
        self._s = 0.0

    def stddev(self):
        """
        Return the standard deviation
        """
        if self.n == 1:
            return 0.0
        return math.sqrt(self._s / (self.n - 1))

    def update(self, value):

        # update stats for new value
        self.n += 1.0
        diff = (value - self.mean)
        self.mean += diff / self.n
        self._s += diff * (value - self.mean)

        if self.n == self.size + 1:
            # update stats for removing old value
            old = self._window.pop(0)
            oldM = (self.n * self.mean - old)/(self.n - 1)
            self._s -= (old - self.mean) * (old - oldM)
            self.mean = oldM
            self.n -= 1

        self._window.append(value)

if __name__ == '__main__':
    # Create an agent
    agent = Agent()

    # Create a handler and pass it an agent so it can write points
    h = TtestHandler(agent)

    # Set the handler on the agent
    agent.handler = h

    # Anything printed to STDERR from a UDF process gets captured into the Kapacitor logs.
    print >> sys.stderr, "Starting agent for TtestHandler"
    agent.start()
    agent.wait()
    print >> sys.stderr, "Agent finished"
