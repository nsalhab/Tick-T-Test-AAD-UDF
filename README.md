# Tick T-Test Autonomous Anomaly Detector User Defined Function (Tick-T-Test-AAD-UDF)
## What is this about?
This is the code of a custom anomaly detection algorithm using
**Welch's t-test for the null hypothesis H0.**
It consists of ***two-sample location test***, used to validate the hypothesis that the related two populations have equal means.

The T-Test code is implemented in **Python** and uses the **scipy stats library**.

## Environment:
Kapacitor is designed to integrate easily with any algorithm that fits specific domains.
In Kapacitor's jargon, these custom algorithms are called **User Defined Functions (UDFs)**.

## How does the algorithm work?
To keep our anomaly detection algorithm simple, let’s compute a **p-value** for each window of data we receive, and then emit a single data point with that p-value. 
To compute the p-value, we use ***Welch’s t-test.*** 
For a null hypothesis, we will state that a new window is from the same population as the historical windows. 
If the **p-value** drops low enough, we can reject the null hypothesis and conclude that the window must be from something different than the historical data population, or an anomaly. 

## What about the operation of the UDF?

Kapacitor will spawn a process called **an agent**. 
The agent is responsible for describing what options it has, and then initializing itself with a set of options. 
As data is received by the UDF, the agent performs its computation and then returns the resulting data to Kapacitor. 
All of this communication occurs over STDIN and STDOUT using **protocol buffers**. 
As of this writing, Kapacitor has agents implemented in Go and Python that take care of the communication details and expose an interface for doing the actual work. 
***For this algorithm, we will be using the Python agent.***



## How to integrate this?
In order to configure Kapacitor for our UDF, we need to add this snippet in the file called 
***kapacitor.conf***
to your Kapacitor configuration file (typically located at */etc/kapacitor/kapacitor.conf*).
In the configuration we called the function **tTest**. That is also how we will reference it in the TICKscript.

Notice that our Python script imported the Agent object, and we set the **PYTHONPATH** in the configuration. 
Clone the Kapacitor source into the tmp dir so we can point the PYTHONPATH at the necessary python code. 
This is typically overkill since it’s just two Python files, but it makes it easy to follow.
