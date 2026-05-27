# Orbit Wars Agent - Orbital Commander (v3.2 Ultimate Edition)

Welcome to the repository of **Orbital Commander**, a highly sophisticated, mathematically optimized AI agent built to dominate in the continuous-space environment of **Orbit Wars** on Kaggle.

This project implements a multi-layered predictive strategy utilizing step-by-step orbital physics prediction, travel-time consistency searches, and dynamic staging ground logistics. In position-rotated cyclic tournaments, the ultimate **v3.2** build achieves an **83.3% Win Rate** against prior iterations and baseline agents, holding the current peak public score of **`674.2`** on the competition leaderboard.

---

## 🌌 Project Architecture

Orbital Commander operates on a highly secure four-phase loop that executes every turn:

### 1. The Physics & Orbit Prediction Engine (`GameState`)
- **Orbital Calculation**: Predicts the exact continuous-space trajectory of rotating planets, stationary planets, and linear comets at any absolute future step.
- **Path-Clearing Projection**: Simulates the flight path of fleets tick-by-tick, validating routes against **Sun collisions** and intermediate **planet interceptions** using continuous-space linear swept-pair collision check approximations.
- **Exact Combat Resolution**: Re-implements the official Kaggle combat interpreter turn-by-turn to predict future garrisons with perfect fidelity.

### 2. Precise Defense Coordination
- **Simulated Garrison Checks**: Scans owned planets up to 25 steps into the future. If a planet is projected to be lost to incoming hostile fleets, it flags a defense request.
- **Distance-Sorted Reinforcements**: Safe midfield and backline planets are sorted by their **exact distance** to the threatened system. Reinforcements are prioritized and dispatched from the **closest safe planets first** to ensure the absolute fastest arrival.

### 3. Decisive Concentrated Offense
- **Consistent Speed Search**: Searches for a mathematically consistent arrival turn where the travel time of the dispatched fleet matches or beats the target's orbital rotation tick.
- **Concentrated Force Principle**: To completely eliminate the risk of *defeat in detail*, offense only dispatches fleets if a single source planet can muster the entire required force to take the target alone.
- **Smarter ROI Target Selection**: Targets are globally evaluated by Return on Investment (ROI). Capturing enemy-owned systems is heavily prioritized (ROI multiplied by 5) over neutrals to choke the enemy's resource generation.

### 4. Secure Backline-to-Frontline Staging Grounds
- **Staging Ground Logistics**: Safely funnels surplus resources from backline planets to frontline staging grounds closest to the enemy.
- **Dynamic Guard Garrison**: Safely retains a defensive guard of 15 ships when near midfield and 10 ships when deep in the backline to secure systems against enemy snipes.
- **Pre-Flight Path Verification**: Funneling fleets are strictly checked for Sun collision and we verify that the destination planet remains friendly at the exact step of arrival.

---

## 📈 Leaderboard Progression

| Version | Description / Strategic Upgrades | Public Score |
| :--- | :--- | :--- |
| **`v3.2` (Latest)** | **Dynamic Reserves, 1-Ship Neutral Capture, Defeat-in-Detail Immunity** | **`674.2`** 🏆 |
| `v3.1` | Coordinated Combat Resolution order matching | `642.6` |
| `v3` | Distance-Sorted Defense and Staging Ground Staging | `654.0` |
| `v2` | Precision Speed Search & Safe Staging ground | `616.3` |
| `v1` | 100% Win Rate vs Sniper baseline | `595.4` |

---

## 📂 Repository Structure

- [main.py](file:///C:/Users/st901/OneDrive/Desktop/Kaggle_orbitwars/main.py): The ultimate production build submitted to Kaggle.
- [main_v3.2.py](file:///C:/Users/st901/OneDrive/Desktop/Kaggle_orbitwars/main_v3.2.py): Development file for the v3.2 model.
- [main_v2.py](file:///C:/Users/st901/OneDrive/Desktop/Kaggle_orbitwars/main_v2.py): Pre-upgrade version.
- [sniper_agent.py](file:///C:/Users/st901/OneDrive/Desktop/Kaggle_orbitwars/sniper_agent.py): Local baseline agent used for initial validation.
- [CHALLENGES.md](file:///C:/Users/st901/OneDrive/Desktop/Kaggle_orbitwars/CHALLENGES.md): A detailed retrospective documenting the problems faced during development and the engineering breakthroughs that solved them.
