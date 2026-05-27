import math
from kaggle_environments.envs.orbit_wars.orbit_wars import Planet, Fleet, CENTER, ROTATION_RADIUS_LIMIT

# Core Physics Parameters
BOARD_SIZE = 100.0
SUN_RADIUS = 10.0
COMET_RADIUS = 1.0


def distance(p1, p2):
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def point_to_segment_distance(p, v, w):
    """Minimum distance from point p to line segment v-w."""
    l2 = (v[0] - w[0]) ** 2 + (v[1] - w[1]) ** 2
    if l2 == 0.0:
        return distance(p, v)
    t = max(
        0, min(1, ((p[0] - v[0]) * (w[0] - v[0]) + (p[1] - v[1]) * (w[1] - v[1])) / l2)
    )
    projection = (v[0] + t * (w[0] - v[0]), v[1] + t * (w[1] - v[1]))
    return distance(p, projection)


def swept_pair_hit(A, B, P0, P1, r):
    """True iff a fleet moving A->B and a planet moving P0->P1 come within r
    of each other for some t in [0, 1]. Treats both segments as linear over
    the tick (planet rotation is linearised to its chord)."""
    d0x, d0y = A[0] - P0[0], A[1] - P0[1]
    dvx = (B[0] - A[0]) - (P1[0] - P0[0])
    dvy = (B[1] - A[1]) - (P1[1] - P0[1])
    a = dvx * dvx + dvy * dvy
    b = 2.0 * (d0x * dvx + d0y * dvy)
    c = d0x * d0x + d0y * d0y - r * r
    if a < 1e-12:
        return c <= 0.0
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return False
    sq = math.sqrt(disc)
    t1 = (-b - sq) / (2.0 * a)
    t2 = (-b + sq) / (2.0 * a)
    return t2 >= 0.0 and t1 <= 1.0


def estimate_fleet_speed(ships, max_speed=6.0):
    """Calculates fleet speed based on the logarithmic curve in rules."""
    if ships <= 1:
        return 1.0
    val = math.log(ships) / math.log(1000)
    if val < 0.0:
        val = 0.0
    speed = 1.0 + (max_speed - 1.0) * (val ** 1.5)
    return min(speed, max_speed)


class GameState:
    def __init__(self, obs):
        self.step = obs.get("step", 0)
        self.player = obs.get("player", 0) if isinstance(obs, dict) else obs.player
        self.angular_velocity = obs.get("angular_velocity", 0.0)

        # Parse planets
        raw_planets = obs.get("planets", []) if isinstance(obs, dict) else obs.planets
        self.planets = [Planet(*p) for p in raw_planets]

        # Parse initial planets
        raw_initial = obs.get("initial_planets", []) if isinstance(obs, dict) else obs.initial_planets
        self.initial_planets = {p[0]: Planet(*p) for p in raw_initial}

        # Parse comet IDs
        self.comet_ids = set(obs.get("comet_planet_ids", []) if isinstance(obs, dict) else obs.comet_planet_ids)

        # Parse comets group data
        self.comets_groups = obs.get("comets", []) if isinstance(obs, dict) else obs.comets

        # Parse fleets
        raw_fleets = obs.get("fleets", []) if isinstance(obs, dict) else obs.fleets
        self.fleets = [Fleet(*f) for f in raw_fleets]

        # Build maps
        self.planet_by_id = {p.id: p for p in self.planets}

        # Precompute comet paths lookup
        self.comet_paths = {}
        for group in self.comets_groups:
            pids = group["planet_ids"]
            paths = group["paths"]
            path_idx = group["path_index"]
            for i, pid in enumerate(pids):
                if i < len(paths):
                    self.comet_paths[pid] = (paths[i], path_idx)

    def predict_planet_pos(self, planet_id, step):
        """Predicts the coordinates of a planet (static, orbiting, or comet) at a future step, using a cache."""
        if not hasattr(self, '_pos_cache'):
            self._pos_cache = {}
        key = (planet_id, step)
        if key in self._pos_cache:
            return self._pos_cache[key]
        res = self._predict_planet_pos_uncached(planet_id, step)
        self._pos_cache[key] = res
        return res

    def _predict_planet_pos_uncached(self, planet_id, step):
        """Predicts the coordinates of a planet (static, orbiting, or comet) at a future step."""
        # If it's a comet
        if planet_id in self.comet_ids:
            if planet_id not in self.comet_paths:
                return None
            path, path_idx = self.comet_paths[planet_id]
            dt = step - self.step
            target_idx = path_idx + dt
            if 0 <= target_idx < len(path):
                return path[target_idx]
            else:
                return None  # Comet has departed

        # Standard planet
        planet = self.planet_by_id.get(planet_id)
        if planet is None:
            return None

        initial_p = self.initial_planets.get(planet_id)
        if initial_p is None:
            return (planet.x, planet.y)

        dx = initial_p.x - CENTER
        dy = initial_p.y - CENTER
        orb_r = math.hypot(dx, dy)
        if orb_r + planet.radius < ROTATION_RADIUS_LIMIT:
            # Orbiting planet - use step-based rotation logic from the engine
            init_angle = math.atan2(dy, dx)
            current_angle = init_angle + self.angular_velocity * max(0, step - 1)
            return (
                CENTER + orb_r * math.cos(current_angle),
                CENTER + orb_r * math.sin(current_angle),
            )
        else:
            # Static planet
            return (planet.x, planet.y)

    def estimate_travel_time(self, from_id, to_id, ships):
        """Estimates the arrival turn of a fleet launched now, considering the target's movement."""
        from_planet = self.planet_by_id.get(from_id)
        to_planet = self.planet_by_id.get(to_id)
        if from_planet is None or to_planet is None:
            return 999

        speed = estimate_fleet_speed(ships)
        # Search for the earliest arrival turn dt (turn offset from current step). Extended range for 4-player maps.
        for dt in range(1, 200):
            target_pos = self.predict_planet_pos(to_id, self.step + dt)
            if target_pos is None:
                break

            # Distance between from_planet center and the target's projected position
            dist = math.hypot(target_pos[0] - from_planet.x, target_pos[1] - from_planet.y)
            # Subtract radius bounds (fleet spawns outside from_planet by R + 0.1)
            effective_dist = dist - from_planet.radius - to_planet.radius - 0.1
            if effective_dist <= 0:
                return dt

            turns_needed = effective_dist / speed
            if dt >= turns_needed:
                return dt
        return 999

    def analyze_active_fleets(self):
        """Identifies target destination and exact arrival step of every active fleet on the board."""
        arrivals = {p.id: [] for p in self.planets}

        for fleet in self.fleets:
            speed = estimate_fleet_speed(fleet.ships)
            fx, fy = fleet.x, fleet.y
            angle = fleet.angle

            # Simulate the flight step-by-step
            for dt in range(1, 120):
                old_fx, old_fy = fx, fy
                fx += math.cos(angle) * speed
                fy += math.sin(angle) * speed
                new_fx, new_fy = fx, fy

                # Check out of bounds
                if not (0 <= new_fx <= BOARD_SIZE and 0 <= new_fy <= BOARD_SIZE):
                    break

                # Check Sun collision
                if point_to_segment_distance((CENTER, CENTER), (old_fx, old_fy), (new_fx, new_fy)) < SUN_RADIUS:
                    break

                # Check planet collisions
                collided_planet_id = None
                for planet in self.planets:
                    p_old = self.predict_planet_pos(planet.id, self.step + dt - 1)
                    p_new = self.predict_planet_pos(planet.id, self.step + dt)
                    if p_old is None or p_new is None:
                        continue
                    if swept_pair_hit((old_fx, old_fy), (new_fx, new_fy), p_old, p_new, planet.radius):
                        collided_planet_id = planet.id
                        break

                if collided_planet_id is not None:
                    arrivals[collided_planet_id].append((self.step + dt, fleet.owner, fleet.ships))
                    break

        return arrivals

    def precompute_garrison_timelines(self, arrivals_map, horizon=65):
        """Precompute future owners and ships for all planets up to horizon steps."""
        self.garrison_cache = {}
        for planet in self.planets:
            timeline = []  # list of (owner, ships) indexed by dt (from 0 to horizon)
            current_owner = planet.owner
            current_ships = planet.ships
            prod = planet.production
            
            incoming = list(arrivals_map.get(planet.id, []))
            
            # Pre-group fleets by step for O(1) lookup
            fleets_by_step = {}
            for f in incoming:
                step = f[0]
                fleets_by_step.setdefault(step, []).append(f)
                
            # Step 0 is the current step
            timeline.append((current_owner, current_ships))
            
            for dt in range(1, horizon + 1):
                step = self.step + dt
                if planet.id in self.comet_ids and self.predict_planet_pos(planet.id, step) is None:
                    # Comet expired
                    timeline.append((-1, 0))
                    current_owner, current_ships = -1, 0
                    continue
                    
                fleets_this_step = fleets_by_step.get(step, [])
                if fleets_this_step:
                    player_ships = {}
                    for _, f_owner, f_ships in fleets_this_step:
                        player_ships[f_owner] = player_ships.get(f_owner, 0) + f_ships
                    sorted_players = sorted(player_ships.items(), key=lambda x: x[1], reverse=True)
                    top_player, top_ships = sorted_players[0]
                    if len(sorted_players) > 1:
                        second_ships = sorted_players[1][1]
                        if top_ships == second_ships:
                            survivor_ships = 0
                            survivor_owner = -1
                        else:
                            survivor_ships = top_ships - second_ships
                            survivor_owner = top_player
                    else:
                        survivor_owner = top_player
                        survivor_ships = top_ships
                    if survivor_ships > 0:
                        if current_owner == survivor_owner:
                            current_ships += survivor_ships
                        else:
                            current_ships -= survivor_ships
                            if current_ships < 0:
                                current_owner = survivor_owner
                                current_ships = abs(current_ships)
                    
                if current_owner != -1:
                    current_ships += prod
                    
                timeline.append((current_owner, current_ships))
            self.garrison_cache[planet.id] = timeline

    def simulate_future_garrison(self, planet_id, target_step, arrivals_map, extra_arrivals=None):
        """Predict owner and ships at target_step, using precomputed timeline if possible."""
        dt = target_step - self.step
        if not extra_arrivals and hasattr(self, 'garrison_cache') and planet_id in self.garrison_cache:
            timeline = self.garrison_cache[planet_id]
            if 0 <= dt < len(timeline):
                return timeline[dt]

        # Fallback to dynamic simulation if extra_arrivals are present or dt is out of range
        planet = self.planet_by_id.get(planet_id)
        if planet is None:
            return -1, 0

        current_owner = planet.owner
        current_ships = planet.ships
        prod = planet.production
        incoming = list(arrivals_map.get(planet_id, []))
        if extra_arrivals:
            incoming.extend(extra_arrivals)

        # Pre-group for speed in dynamic fallback
        fleets_by_step = {}
        for f in incoming:
            fleets_by_step.setdefault(f[0], []).append(f)

        for step in range(self.step + 1, target_step + 1):
            if planet_id in self.comet_ids and self.predict_planet_pos(planet_id, step) is None:
                return -1, 0

            fleets_this_step = fleets_by_step.get(step, [])
            if fleets_this_step:
                player_ships = {}
                for _, f_owner, f_ships in fleets_this_step:
                    player_ships[f_owner] = player_ships.get(f_owner, 0) + f_ships
                sorted_players = sorted(player_ships.items(), key=lambda x: x[1], reverse=True)
                top_player, top_ships = sorted_players[0]
                if len(sorted_players) > 1:
                    second_ships = sorted_players[1][1]
                    if top_ships == second_ships:
                        survivor_ships = 0
                        survivor_owner = -1
                    else:
                        survivor_ships = top_ships - second_ships
                        survivor_owner = top_player
                else:
                    survivor_owner = top_player
                    survivor_ships = top_ships
                if survivor_ships > 0:
                    if current_owner == survivor_owner:
                        current_ships += survivor_ships
                    else:
                        current_ships -= survivor_ships
                        if current_ships < 0:
                            current_owner = survivor_owner
                            current_ships = abs(current_ships)

            if current_owner != -1:
                current_ships += prod

        return current_owner, current_ships

    def is_path_clear(self, from_id, to_id, travel_time, ships):
        """Checks if a planned fleet route is safe from Sun collision and planet interceptions."""
        from_planet = self.planet_by_id.get(from_id)
        to_planet = self.planet_by_id.get(to_id)
        if from_planet is None or to_planet is None:
            return False

        target_pos = self.predict_planet_pos(to_id, self.step + travel_time)
        if target_pos is None:
            return False

        angle = math.atan2(target_pos[1] - from_planet.y, target_pos[0] - from_planet.x)
        speed = estimate_fleet_speed(ships)

        fx = from_planet.x + math.cos(angle) * (from_planet.radius + 0.1)
        fy = from_planet.y + math.sin(angle) * (from_planet.radius + 0.1)

        for dt in range(1, travel_time + 1):
            old_fx, old_fy = fx, fy
            if dt == travel_time:
                fx, fy = target_pos[0], target_pos[1]
            else:
                fx += math.cos(angle) * speed
                fy += math.sin(angle) * speed
            new_fx, new_fy = fx, fy

            # Sun Check with small safety buffer
            if point_to_segment_distance((CENTER, CENTER), (old_fx, old_fy), (new_fx, new_fy)) < SUN_RADIUS + 0.1:
                return False

            # Intermediate planet check
            for planet in self.planets:
                if planet.id == from_id or planet.id == to_id:
                    continue
                p_old = self.predict_planet_pos(planet.id, self.step + dt - 1)
                p_new = self.predict_planet_pos(planet.id, self.step + dt)
                if p_old is None or p_new is None:
                    continue
                if swept_pair_hit((old_fx, old_fy), (new_fx, new_fy), p_old, p_new, planet.radius):
                    return False

        return True


def agent(obs):
    state = GameState(obs)
    arrivals = state.analyze_active_fleets()
    state.precompute_garrison_timelines(arrivals, horizon=65)

    # 1. Coordinate Defense
    defense_needs = {}
    my_planets = [p for p in state.planets if p.owner == state.player]

    for mine in my_planets:
        # Check if the planet will be lost to enemy fleets in the next 25 steps
        for dt in range(1, 25):
            future_owner, future_ships = state.simulate_future_garrison(mine.id, state.step + dt, arrivals)
            if future_owner != state.player:
                # We need reinforcements arriving before or at step + dt
                defense_needs[mine.id] = (future_ships + 1, state.step + dt)
                break

    # Calculate safe, allocatable ships on each of our planets
    available_ships = {}
    for mine in my_planets:
        if mine.id in defense_needs:
            available_ships[mine.id] = 0
        else:
            available_ships[mine.id] = mine.ships

    moves = []

    # Process defense requests: reinforce from closest safe planets
    for def_id, (needed_ships, limit_step) in sorted(defense_needs.items(), key=lambda x: x[1][1]):
        for mine in my_planets:
            if mine.id == def_id or available_ships.get(mine.id, 0) <= 0:
                continue

            # Start with maximum possible reinforcement size to see if it's feasible
            max_send = min(available_ships[mine.id], needed_ships)
            if max_send <= 0:
                continue

            # Calculate actual travel time if we send max_send
            travel_time = state.estimate_travel_time(mine.id, def_id, max_send)
            if state.step + travel_time <= limit_step:
                if state.is_path_clear(mine.id, def_id, travel_time, max_send):
                    target_pos = state.predict_planet_pos(def_id, state.step + travel_time)
                    if target_pos is not None:
                        angle = math.atan2(target_pos[1] - mine.y, target_pos[0] - mine.x)
                        moves.append([mine.id, angle, max_send])
                        available_ships[mine.id] -= max_send
                        needed_ships -= max_send
                        if needed_ships <= 0:
                            break

    # 2. Coordinate Offense using Consistent Speed Search
    targets = [p for p in state.planets if p.owner != state.player]
    attack_options = []

    for mine in my_planets:
        ships_avail = available_ships.get(mine.id, 0)
        if ships_avail <= 0:
            continue

        for target in targets:
            # If target is a comet, filter out if it is about to depart
            if target.id in state.comet_ids:
                if target.id not in state.comet_paths:
                    continue
                path, path_idx = state.comet_paths[target.id]
                steps_left = len(path) - path_idx
                est_t = state.estimate_travel_time(mine.id, target.id, ships_avail)
                if steps_left < est_t + 5:  # Require at least 5 turns of active life after arrival
                    continue

            # Search for a mathematically consistent arrival turn dt
            opt_t = None
            opt_ships = None
            for dt in range(1, 40):
                future_owner, future_ships = state.simulate_future_garrison(target.id, state.step + dt, arrivals)
                if future_owner == state.player:
                    break  # Already projected to be captured

                ships_needed = future_ships + 1
                if ships_needed > ships_avail:
                    continue

                # Actual travel time when sending exactly ships_needed
                act_t = state.estimate_travel_time(mine.id, target.id, ships_needed)
                if act_t <= dt:
                    # Consistent! Ships needed can arrive at or before dt
                    opt_t = act_t
                    opt_ships = ships_needed
                    break

            if opt_ships is not None and opt_ships > 0:
                if state.is_path_clear(mine.id, target.id, opt_t, opt_ships):
                    # Compute relative Return on Investment (ROI)
                    val = target.production
                    if target.owner != -1:
                        val *= 2  # Capturing from enemy shifts production balance doubly
                    roi = val / opt_ships
                    attack_options.append({
                        "from_id": mine.id,
                        "to_id": target.id,
                        "ships": opt_ships,
                        "travel_time": opt_t,
                        "roi": roi,
                    })

    # Sort attack decisions globally by ROI descending
    attack_options.sort(key=lambda x: x["roi"], reverse=True)

    targeted_planets = set()
    for opt in attack_options:
        from_id = opt["from_id"]
        to_id = opt["to_id"]
        ships = opt["ships"]
        travel_time = opt["travel_time"]

        if to_id in targeted_planets:
            continue
        if available_ships.get(from_id, 0) < ships:
            continue

        target_pos = state.predict_planet_pos(to_id, state.step + travel_time)
        if target_pos is not None:
            angle = math.atan2(target_pos[1] - state.planet_by_id[from_id].y, target_pos[0] - state.planet_by_id[from_id].x)
            moves.append([from_id, angle, ships])
            available_ships[from_id] -= ships
            targeted_planets.add(to_id)

    # 3. Safe Backline-to-Frontline Resource Consolidation
    enemy_planets = [p for p in state.planets if p.owner != state.player and p.owner != -1]
    if enemy_planets:
        for mine in my_planets:
            ships_left = available_ships.get(mine.id, 0)
            # Retain a baseline guard garrison of 15 ships to prevent simple snipes
            if ships_left > 15:
                surplus = ships_left - 15
                
                # Calculate mine's distance to nearest enemy
                mine_min_enemy_dist = min(math.hypot(mine.x - e.x, mine.y - e.y) for e in enemy_planets)
                
                # Find a frontline planet we own that is significantly closer to enemies
                best_dest = None
                best_closeness_diff = 10.0  # Must be at least 10 units closer to enemy than mine
                
                for dest in my_planets:
                    if dest.id == mine.id:
                        continue
                    dest_min_enemy_dist = min(math.hypot(dest.x - e.x, dest.y - e.y) for e in enemy_planets)
                    closeness_diff = mine_min_enemy_dist - dest_min_enemy_dist
                    if closeness_diff > best_closeness_diff:
                        best_dest = dest
                        best_closeness_diff = closeness_diff
                
                if best_dest is not None:
                    # Reinforce the frontline staging ground!
                    travel_time = state.estimate_travel_time(mine.id, best_dest.id, surplus)
                    if travel_time < 50:
                        if state.is_path_clear(mine.id, best_dest.id, travel_time, surplus):
                            dest_pos = state.predict_planet_pos(best_dest.id, state.step + travel_time)
                            if dest_pos is not None:
                                angle = math.atan2(dest_pos[1] - mine.y, dest_pos[0] - mine.x)
                                moves.append([mine.id, angle, surplus])
                                available_ships[mine.id] -= surplus

    return moves
