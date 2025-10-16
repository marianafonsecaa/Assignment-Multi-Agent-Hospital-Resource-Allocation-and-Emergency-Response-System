# Assignment-Multi-Agent-Hospital-Resource-Allocation-and-Emergency-Response-System


# Multi-Agent Hospital Resource Allocation and Emergency Response System

## 1. Overview

This project aims to design and implement a **decentralized hospital resource allocation and emergency response system** using the **SPADE** framework.  
The system simulates a healthcare network where autonomous agents—hospitals, ambulances, doctors, and supply units—collaborate to manage patient flow and allocate resources efficiently in real time, **without a central coordinating entity**.

The motivation for this work lies in the limitations of centralized hospital management systems, which often become bottlenecks during crisis situations such as epidemics, mass accidents, or sudden surges in patient demand.  
By adopting a **multi-agent system (MAS)** approach, the project explores the potential of distributed coordination and negotiation to enhance resilience, scalability, and fairness in healthcare delivery.

---

## 2. Problem Description

Healthcare systems frequently encounter unpredictable fluctuations in patient inflow and resource availability.  
In centralized management structures, decision-making delays can lead to inefficient utilization of resources and increased patient waiting times.

This work proposes a decentralized, agent-based model where each hospital, ambulance, and supply unit acts as an autonomous decision-making entity capable of:
- Exchanging real-time information about local resources (beds, staff, medical supplies);
- Negotiating and collaborating with other agents;
- Adapting dynamically to changing environmental conditions and emergencies.

---

## 3. System Architecture

The system is composed of multiple agent types, each with specific roles and responsibilities:

### 3.1 Hospital Agents
- Represent hospital facilities with finite capacity in terms of beds, staff, and supplies.  
- Evaluate incoming patient requests and decide whether to admit or redirect patients.  
- Coordinate with other hospitals and ambulances through peer-to-peer communication.  
- Monitor local resource levels and ensure balanced resource utilization.

### 3.2 Ambulance Agents
- Simulate patient transport between hospitals.  
- Determine the optimal destination hospital based on proximity, resource availability, and patient condition.  
- React dynamically to changes in hospital status and resource levels.

### 3.3 Doctor/Nurse Agents
- Represent medical personnel with limited workload capacity.  
- Prioritize patients according to severity and treatment urgency.  
- Communicate with hospital agents to update treatment progress and availability.

### 3.4 Supply Agents
- Manage the distribution of essential resources such as oxygen, medication, and protective equipment.  
- Respond to hospital requests for replenishment and coordinate delivery under constraints.  
- Contribute to system resilience by mitigating supply shortages.

---

## 4. Core Functionalities

1. **Decentralized Coordination:**  
   The system operates without a central control authority, relying instead on agent-to-agent communication and negotiation mechanisms.

2. **Dynamic Environment:**  
   Patient arrivals and emergencies occur randomly over time, requiring adaptive behavior from all agents.

3. **Contract Net Protocol (CNP):**  
   Applied for decentralized task delegation and negotiation. For instance, when a hospital cannot admit a patient, it issues a call for proposals to other hospitals.

4. **Resource Management:**  
   Agents monitor and allocate resources (beds, staff hours, supplies) to optimize efficiency and fairness.

5. **Real-Time Collaboration:**  
   All agents maintain updated knowledge about system status through continuous message exchange.

---

## 5. Performance Evaluation

The performance of the system is assessed through the following metrics:

| Metric | Description |
|--------|-------------|
| **Patients Treated** | Total number of patients successfully admitted and treated |
| **Average Waiting and Transport Time** | Time elapsed from patient request to hospital admission |
| **Resource Utilization** | Percentage of beds, staff, and supplies used over time |
| **Fairness Index** | Measure of equity in resource distribution across hospitals |
| **Emergency Responsiveness** | System’s capacity to handle sudden surges or crises |

---

## 6. Agent Role Summary

| Agent Type | Function |
|-------------|-----------|
| Hospital | Manage admissions, monitor resources, negotiate with peers |
| Ambulance | Optimize patient routing and transport logistics |
| Doctor/Nurse | Prioritize and treat patients according to severity |
| Supplier | Allocate and distribute medical supplies across the network |

---

## 7. Development Phases

### Phase 1 (Weeks 1–2)
- Study of multi-agent systems and the SPADE framework.  
- Definition of system architecture, communication protocols, and environment.  
- Implementation of initial versions of hospital and ambulance agents.

### Phase 2 (Week 3)
- Establish inter-agent communication between hospitals and ambulances.  
- Implement basic patient routing and admission logic.

### Phase 3 (Week 4)
- Integrate resource constraints (beds, staff, supplies).  
- Introduce dynamic patient arrivals and emergency events.

### Phase 4 (Week 5)
- Implement the Contract Net Protocol for distributed negotiation.  
- Extend the system with supply agents and staff prioritization mechanisms.

### Phase 5 (Week 6)
- Develop a visualization module for monitoring hospitals, ambulances, and resources.  
- Conduct experimental testing under different scenarios (epidemic surge, supply shortage, mass accident).  
- Evaluate system performance based on the defined metrics.
