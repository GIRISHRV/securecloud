# SecureCloud: Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation

Aditya Rajendra Melavanki, Abhishek Suryanarayana Bhat, Aditya B N, Girish R V, and Dr. S. Anthoniraj

School of Computer Science and Engineering, JAIN (Deemed-to-be University)

## Abstract

Kubernetes adapted environments are used by many organizations, which implement some degree of self-service capabilities for the implementation of the control process to avoid lateral movement once an attack has occurred. One of the major providers of this technology is SecureCloud, which developed an Azure-like interface combined with a zero-trust security technology. The provisioning process here is a limited process that refers to the sharing of workloads of end-users from the allowlist while the implementation of the Kubernetes technology is carried out through a secured API. Cilium is able to provide efficient communication between nodes and Hubble enables monitoring of the process.

The purpose of the created temporal engine is to analyze workloads depicted as nodes and show the connection between different related ranges. Thus, the goal of the model becomes predicting and tracking risk related to anomaly accumulation. Thus, the risk of temporal engine is connected to policies being refused within the attempts of violating other tenants, scanning behaviour as well as other worker nodes. The function is also aimed at determining situations when the risk was triggered. A total of 12 cases with 30 repetitions and 5 random seeds were evaluated offline. In total, 1800 case runs were created. The results of temporal engine were measured as follows: precision-0.923; recall-0.923; F1-0.923. Edge frequency baseline results were 1.000 in terms of accuracy, while recall and F1 were 0.846 and 0.917 respectively.

**Index Terms—** zero trust, temporal graph neural network, lateral movement, Kubernetes, Cilium, Hubble, anomaly detection

## I. Introduction

Cloud-native technology allows for a common orchestration context of cloud applications and actions within the cloud. In fact, entry for the hacker remains intact because the hacker can use a legitimate and authorized application to penetrate the cloud. Zero trust principles oppose the concept of implicity trust based on the location of the device within the network [1], [2]. However, still, the cloud platform has to evaluate every relationship based on its identity and policies. Furthermore, the old static policy remains important because some outgoing communication actions should not have been even established. Nevertheless, policies cannot provide answer concerning behavior of authorized communications.

It is important to identify a method for linking detection and representation of power.

SecureCloud can do so by implementing a private cloud portal and using the secure plane.

Specifically, the tenants are created by users; they set up the workloads that they are allowed to execute.

The middleware converts the approved intent to the Cilium policy and to that of Kubernetes.

The next stage is the Hubble flow ingestion and getting the workload communication assessment through the temporal graph model.

This research shows how temporal link prediction can improve detection compared to ordinary edge frequency benchmark. Two different arrangements can have similar sequences of events and their associated policies. The assessment tests whether the information received from the detectors can be used to validate a zero-trust response process. This contribution constitutes the assessment of a model that is functioning. There is no implication of innovation concerning the techniques involved. SecureCloud provides stable graphs of workload identity as well as risk correlation with policies, thus achieving a reliable ratio of 1800 to 1. The above provides measurable trade offs of recall and false positives.

## II. Related Work

The affiliated work will define zero trust as architecture according to NIST SP 800-207 and will get rid of the idea of blind trust based on either the location of the network or the geographical location. The model developed in NIST SP 800-207A is going to be utilized for identifying applications in the area of cloud computing. The documents under consideration will present identity and least privilege of the process.

Kubernetes network policy is able to grant ingress and egress isolation. Cilium provides access to deny policies and therefore the rules used in this case are preferred to the rules limiting the access. Hubble will be able to demonstrate the data plane flows.

Such types of services can help in bringing ideas to action, yet they are incapable of keeping track of time developments. The work done by Euler belongs to practices where graph modeling is used to describe communication in organisations. He argues that such moving means exchanging low probability links of the future. Convolutional graph neural networks ensure that the connection is established between the fact that it is graph and recurrent states. A family of such models provides for reproducibility of experiments. SecureCloud uses temporal link prediction for trustworthy application workloads.

Additionally, the system has been provided with a policy called the fact gate. The identified risk could lead to a case which requires a review. The middleware does recommend containment only when the risk is still present and there is a secure fact.

## III. System Architecture

The management plane is composed of a portal created using React and TypeScript. The control APIs are implemented using the FastAPI modular monolith and SQLite is used for local data storing. The API functionality includes handling sessions, tenants, and roles, auditing, and managing operational processes.

Users of the portal are allowed to only choose the templates and not submit the raw YAML files. The adapter is responsible for reconciling the requested templates with available resources. There is a separation of the requested and observed state. Infrastructure proof absence leads to an unclear outcome that the API does not turn into a successful model.

The security layer resolves workload identity, creates rules, and collects flows. It also builds deterministic intervals of 30 seconds and directed graphs. The temporal data analysis will reveal the anomaly in the link while the risk layer will correlate the obtained results to some facts. Therefore, replacement pods keep being contained.

| Plane | Components | Output |
|---|---|---|
| Management | React, FastAPI, SQLite | Authorized desired state |
| Infrastructure | K3s, Kubernetes API | Observed workloads |
| Enforcement | Cilium policy | Allow/deny verdict |
| Detection | Hubble, GConvGRU, risk | Scored evidence |
| Response | Incident adapter | Quarantine/restore state |

## IV. Temporal-Graph Risk Engine

### A. Graph Construction

The directed snapshots utilize SecureCloud workload IDs, which act as stable nodes. The nodes features consist of type of template and logarithmic inbound and outbound counts. The features are formed by denied-flow ratio, unique destination count, unique destination-port count, running state, and quarantine state. The relationship features show same-tenant status, allowed intent, policy-denied ratio, and cross-tenant status. This framework does not learn any names of tenants or any type of tenant identifications; consequently, feature schema is not determined by labeling of any demonstration tenants.

### B. Forecasting the Link and Calibration Process

The Chebyshev graph convolution is used in conjunction with GRU(s) to capture the consecutive events. A directed multilayer decoder will forecast the probability of the forthcoming window for all the source–destination combinations. The anomaly score will be determined by subtracting that probability from one. Each of the samples used in the training stage has one directed edge missing for one of the positive ones in the forthcoming window. The entire experiment is timely divided into 60% for training, 20% for calibration, and 20% for testing. In the threshold, the calibration normal classification score is taken as reference value at 95% percentile.

The process of calibration establishes both an upper and a lower limit for the threshold, which is defined as falling into the range of [0.5, 0.99].

### C. Correlation and Reaction to Risk

The risk is defined by SecureCloud as the following: r(t)=αa(t)+(1−α)r(t−1). The meaning of a(t) here is the link anomaly. The key aspects of this term are the denial of policies and the cross-tenancy coverage. The analysis also includes distortion of horizontal fan-out and vertical port fan-out as well as misuse intentions revealed through the analysis. Besides, the newly learned alert is available for analysis. The middleware suggests that, in the case of a danger pattern, the program offers and acts upon containment solutions based on the available independent evidence. The model of the program does not allow for policy development. During the course of the allowed operation, any previous state is collected.

## V. Experimental Method

The 12 scenarios that have been subjected to the experiment can be categorized into 5 benign scenarios which include regular traffic, normal peaks, rebooting, permitted deployment, and temporary malfunction. Whereas 7 out of the 12 scenarios refer directly to dishonest behavior such as cross-tenant access, horizontal scanning, vertical port scanning, unintended destinations, slowness, authorized channel abuse, and movement of a vendor.

Each scenario has gone through a complete implementation of 30 iterations using 5 seeds. The output of the experiment is 1800 executions for every configuration of the detector. The temporal and frequency configurations undergo the same procedures and the static policy using the same scenarios.

The training of the temporal encoder has been completed after 80 epochs of learning. The method for which Adam was utilized assigns a learning rate of 0.01 and weight decay of 0.0001. The paper suggests an analysis performed on several metrics including precision, recall, F1, false-positive rate, average precision, detection latency, and local execution time.

The frequency baseline shows likelihood of the edges by counting their benign occurrences. Experiments have been performed on static-policy prevention tests separately. The selected scenarios were those in which edges were used suspiciously without being prevented by such policies, as not every incident had malicious labels that would allow it to be prevented.

## VI. Results

| Method | Prec. | Recall | F1 | FPR | AP | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Frequency | 1.000 | .846 | .917 | .000 | .880 | 28.0 s |
| Temporal | .923 | .923 | .923 | .091 | .771 | 28.3 s |

The temporal engine, according to the table presented, led to an increase in recall from 0.846 to 0.923. Furthermore, F1 grew from 0.917 to 0.923. The biggest improvement at the scenario level was noticed in the vertical port scanning case, with temporal recall reaching the maximum value of 1.000, while the baseline recall was equal to 0.000.

Note that due to the use of both temporal and relational features, it was possible to establish a pattern which could not have been noticed using frequency novelty. It should be noted that the temporal approach does not lead to improvements in all metrics. For instance, FPR increased from 0.000 to 0.091 (with the corresponding 95% interval equal to 0.078–0.106), while AP dropped from 0.880 to 0.771.

Mean time of scenario inference increased from 0.063 ms to 8.101 ms, while average time spent on temporal training was equal to 7212 ms for each seed. Testing the detectors, it becomes evident that both detectors reject the case of suspicious utilization of an allowed path in the given scenario. Static policy, in his turn, made it possible to prevent all occurrences of cross-tenant-attempt events.

The micro prevention rate is 0.252 as the denominator includes events labeled malicious but allowed by the policy. Also, the macro prevention rate for suspicious cases is 0.839.

## VII. Discussion and Threats to Validity

There are complementary functions performed by policy and behavioral detection in SecureCloud products. Policy detects forbidden paths and temporal scoring evaluates the abnormal usage of allowed paths. The legitimate operation and audit trail withdraws the workloads from the sources.

The higher temporal recall means more false positive hits and lower quality of ranking. It implies that there must be more work on calibration instead of replacing deterministic policies. The independent fact gate limits the automatic reaction at the moment when the model is the only evidence.

Project events and small size of the topology cut the internal validity. The chronological splits do not allow any direct leakage of the future window. Nevertheless, the repeating scenario templates may result in related runs.

The explicit fact risk floor does not allow to escape the effect of the construct validity. The system was evaluated as temporal graph risk engine and not as pure link prediction system. The external validity remains on the K3s local lab only.

The experiment did not measure live containment time or recovery time and overhead. Offline latency does not allow for assessing these things. The public report on the breach that happened in Target store back in 2013 was the starting point for the vendor’s story.

SecureCloud does not replicate the unknown past escalation path. The demonstration traffic is confined to the laboratory belonging to the project.

## VIII. Conclusion

SecureCloud combines limited self-service provisioning with real-time zero-trust policies, Hubble evidence, temporal graph detection, and reversible incident response. The temporal engine has better recall as it detects vertical port scans that have been missed by frequency-based methods. The downside is 0.091 FPR and lower average precision.

The next assessment should make use of more benign data that has been obtained through the use of the same static policies. It also should assess present containment, recovery, and resource overhead.
