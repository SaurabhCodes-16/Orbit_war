# Technical Retrospective: Challenges Faced & Strategic Breakthroughs

Developing a top-tier continuous-space agent for **Orbit Wars** came with major physics, logistic, and game-theoretic challenges. Below is a detailed record of the key roadblocks faced during the development of **Orbital Commander** and the strategic breakthroughs that solved them.

---

##  Challenge 1: The Coordinated Offense "Defeat in Detail" Fiasco

### The Problem:
In `v3.1`, we attempted to enable "coordinated attacks" for offense: if a single planet did not have enough ships to capture a target, it would launch a smaller fleet anyway, hoping other planets would contribute.
However, because the source planets were at different distances, their fleets traveled at different speeds and **arrived at different steps**. In 4-player games, this was disastrous: hostile players would easily capture the target first or wipe out our incoming 5-ship fleet, and then comfortably wait to destroy our next 6-ship fleet arriving 5 turns later. We were actively draining our own defense garrisons to feed the enemy easy, sequential victories.

### The Breakthrough:
We strictly restored the **concentrated force principle** for offense. The agent is now prohibited from launching an attack unless a **single source planet** can muster the entire required force to take the target alone. This ensures all attacks are decisive, massive, single-tick impacts that are highly immune to interception and defeat in detail. Coordinated reinforcement is kept *only* for defense, where sequential arrivals naturally stack safely at our own systems.

---

##  Challenge 2: Early-Game Stifling via Static Reserves

### The Problem:
To protect planets against surprise enemy snipes, we originally enforced a static reserve limit (`MIN_RESERVE = 8`) on all owned systems.
In the high-speed opening expansion phase of a 4-player match, this reserve was a massive handicap. Newly captured neutral planets were completely paralyzed—they couldn't launch any fleets or contribute to expansion until they slowly accumulated more than 8 ships. This allowed aggressive, zero-reserve enemies to sweep the board and choke our economy.

### The Breakthrough:
We engineered **dynamic reserve scaling**. Reserves are set to **0 in the first 130 steps** of the game. This frees up every single ship during the opening neutral land grab, enabling our planets to be highly aggressive and capture key systems before the competition can establish a presence. The reserve limit of 8 is only restored once we enter the mid-game phase and have established stable territory.

---

##  Challenge 3: Resource Waste in Neutral Colonization

### The Problem:
To ensure our attacks on enemy systems were strong enough to withstand incoming enemy reinforcements, we used a minimum attack size floor (`MIN_ATTACK_BATCH = 15`).
However, applying this floor indiscriminately to **neutral planets** was incredibly wasteful. If a nearby neutral planet had **0 garrison**, the actual requirement to capture it was only **1 ship**. Because of the hard batch floor, the agent would waste **15 ships** on it! A planet with 20 ships could only capture 1 neutral instead of spreading out to efficiently capture 3 or 4, severely limiting our expansion speed.

### The Breakthrough:
We implemented **dynamic attack-size scaling** based on target ownership:
- **Neutral Targets (`target.owner == -1`)**: The batch floor is bypassed, and the agent attacks with the **exact minimum force needed** (1 ship for empty neutrals), maximizing speed and colonization efficiency.
- **Enemy Targets (`target.owner != -1`)**: The `MIN_ATTACK_BATCH` floor is strictly enforced to ensure the takeover fleet is powerful enough to hold the system against hostile production.

---

##  Challenge 4: Garrison Simulation Order Mismatch

### The Problem:
In the early versions of our garrison simulation, the order of events calculated production *before* resolving incoming fleet combat.
According to the official Orbit Wars rules, combat is resolved *before* production occurs. This slight physics mismatch caused our consistent-speed search engine to systematically miscalculate future garrisons, causing us to launch attacks that arrived with slightly fewer ships than needed, or over-reinforce safe systems.

### The Breakthrough:
We corrected the simulation loop in `simulate_future_garrison` to perfectly match the Kaggle interpreter:
1. **Combat Resolution**: Resolves all incoming player forces simultaneously, resolving combat outcomes.
2. **Production**: Adds planet ship production *after* the combat outcome has settled.

This 100% physics alignment resulted in flawless predictive accuracy.

---

##  Challenge 5: Travel Distance Blindness on 4-Player Maps

### The Problem:
Our consistent-speed search was originally capped at a search range of 60 steps (`for dt in range(1, 60)`).
On the significantly larger maps typical of 4-player games, planets are spread out much farther. A cap of 60 turns meant the agent was completely blind to distant planets, rendering it unable to compute paths or launch attacks against opponents across the board.

### The Breakthrough:
We extended the search range in `estimate_travel_time` to **200 steps**. This expanded tactical horizon allows the agent to comfortably plan long-range, continuous-space captures across the entire map, guaranteeing we are never locked out of targets.
