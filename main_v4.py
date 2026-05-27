import math
from kaggle_environments.envs.orbit_wars.orbit_wars import (
    Planet,
    Fleet,
    CENTER,
    ROTATION_RADIUS_LIMIT,
)

BOARD_SIZE = 100.0
SUN_RADIUS = 10.0
MAX_FLEET_SPEED = 6.0
GAME_LENGTH = 500

MIN_RESERVE = 8
MIN_ATTACK_BATCH = 15


def distance(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def point_to_segment_distance(p, v, w):
    """Minimum distance from point p to line segment v-w."""
    l2 = (v[0] - w[0]) ** 2 + (v[1] - w[1]) ** 2
    if l2 == 0.0:
        return distance(p, v)
    t = max(
        0.0,
        min(
            1.0,
            ((p[0] - v[0]) * (w[0] - v[0]) + (p[1] - v[1]) * (w[1] - v[1])) / l2,
        ),
    )
    projection = (v[0] + t * (w[0] - v[0]), v[1] + t * (w[1] - v[1]))
    return distance(p, projection)


def swept_pair_hit(A, B, P0, P1, r):
    """True iff moving fleet segment A->B and moving planet P0->P1 come within r."""
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


def estimate_fleet_speed(ships, max_speed=MAX_FLEET_SPEED):
    """Fleet speed from the official logarithmic speed curve."""
    if ships <= 1:
        return 1.0
    val = max(0.0, math.log(max(1, ships)) / math.log(1000))
    return min(1.0 + (max_speed - 1.0) * (val ** 1.5), max_speed)


class GameState:
    def __init__(self, obs):
        self.obs = obs
        self.step = obs.get("step", 0) if isinstance(obs, dict) else getattr(obs, "step", 0)
        self.player = obs.get("player", 0) if isinstance(obs, dict) else obs.player
        self.angular_velocity = (
            obs.get("angular_velocity", 0.0) if isinstance(obs, dict) else obs.angular_velocity
        )

        raw_planets = obs.get("planets", []) if isinstance(obs, dict) else obs.planets
        self.planets = [Planet(*p) for p in raw_planets]

        raw_initial = obs.get("initial_planets", []) if isinstance(obs, dict) else getattr(obs, "initial_planets", [])
        self.initial_planets = {p[0]: Planet(*p) for p in raw_initial}

        self.comet_ids = set(
            obs.get("comet_planet_ids", []) if isinstance(obs, dict) else getattr(obs, "comet_planet_ids", [])
        )
        self.comets_groups = obs.get("comets", []) if isinstance(obs, dict) else getattr(obs, "comets", [])

        raw_fleets = obs.get("fleets", []) if isinstance(obs, dict) else obs.fleets
        self.fleets = [Fleet(*f) for f in raw_fleets]

        self.planet_by_id = {p.id: p for p in self.planets}
        self.comet_paths = {}
        for group in self.comets_groups:
            pids = group.get("planet_ids", [])
            paths = group.get("paths", [])
            path_idx = group.get("path_index", 0)
            for i, pid in enumerate(pids):
                if i < len(paths):
                    self.comet_paths[pid] = (paths[i], path_idx)

        self.turns_left = GAME_LENGTH - self.step
        self.endgame = self.turns_left < 100

        self.effective_reserve = 0 if (self.step < 130 or self.endgame) else MIN_RESERVE

    def predict_planet_pos(self, planet_id, step):
        """Predict planet/comet position at an absolute future step, using a local cache."""
        if not hasattr(self, '_pos_cache'):
            self._pos_cache = {}
        key = (planet_id, step)
        if key in self._pos_cache:
            return self._pos_cache[key]
        res = self._predict_planet_pos_uncached(planet_id, step)
        self._pos_cache[key] = res
        return res

    def _predict_planet_pos_uncached(self, planet_id, step):
        """Predict planet/comet position at an absolute future step."""
        if planet_id in self.comet_ids:
            if planet_id not in self.comet_paths:
                return None
            path, path_idx = self.comet_paths[planet_id]
            target_idx = path_idx + (step - self.step)
            if 0 <= target_idx < len(path):
                return tuple(path[target_idx])
            return None

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
            init_angle = math.atan2(dy, dx)
            current_angle = init_angle + self.angular_velocity * max(0, step - 1)
            return (CENTER + orb_r * math.cos(current_angle), CENTER + orb_r * math.sin(current_angle))

        return (planet.x, planet.y)

    def launch_pos(self, from_id, angle, step=None):
        """Fleet spawn point just outside source planet radius."""
        planet = self.planet_by_id[from_id]
        if step is None:
            step = self.step
        src = self.predict_planet_pos(from_id, step) or (planet.x, planet.y)
        return (
            src[0] + math.cos(angle) * (planet.radius + 0.1),
            src[1] + math.sin(angle) * (planet.radius + 0.1),
        )

    def estimate_travel_time(self, from_id, to_id, ships):
        """Earliest arrival tick offset if launched now."""
        from_planet = self.planet_by_id.get(from_id)
        to_planet = self.planet_by_id.get(to_id)
        if from_planet is None or to_planet is None:
            return 999

        speed = estimate_fleet_speed(ships)
        src_pos = self.predict_planet_pos(from_id, self.step) or (from_planet.x, from_planet.y)

        for dt in range(1, 200):
            target_pos = self.predict_planet_pos(to_id, self.step + dt)
            if target_pos is None:
                break
            dist = distance(src_pos, target_pos)
            effective_dist = dist - from_planet.radius - to_planet.radius - 0.1
            if effective_dist <= 0:
                return dt
            if dt >= effective_dist / speed:
                return dt
        return 999

    def analyze_active_fleets(self):
        """Predict the planet and absolute step each existing fleet will hit.
        FIX 6: Extended from 120 to 210 steps to catch slow long-range fleets.
        """
        arrivals = {p.id: [] for p in self.planets}

        for fleet in self.fleets:
            speed = estimate_fleet_speed(fleet.ships)
            fx, fy = fleet.x, fleet.y
            angle = fleet.angle

            # FIX 6: was range(1, 120) — missed slow fleets on large maps
            for dt in range(1, 210):
                old_fx, old_fy = fx, fy
                fx += math.cos(angle) * speed
                fy += math.sin(angle) * speed
                new_fx, new_fy = fx, fy

                if not (0 <= new_fx <= BOARD_SIZE and 0 <= new_fy <= BOARD_SIZE):
                    break

                if point_to_segment_distance((CENTER, CENTER), (old_fx, old_fy), (new_fx, new_fy)) < SUN_RADIUS:
                    break

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

    @staticmethod
    def resolve_combat(current_owner, current_ships, fleet_forces):
        """Official-style combat."""
        if not fleet_forces:
            return current_owner, current_ships

        sorted_forces = sorted(fleet_forces.items(), key=lambda x: x[1], reverse=True)
        top_owner, top_ships = sorted_forces[0]

        if len(sorted_forces) > 1:
            second_ships = sorted_forces[1][1]
            if top_ships == second_ships:
                return current_owner, current_ships
            survivor_owner = top_owner
            survivor_ships = top_ships - second_ships
        else:
            survivor_owner = top_owner
            survivor_ships = top_ships

        if survivor_ships <= 0:
            return current_owner, current_ships

        if survivor_owner == current_owner:
            return current_owner, current_ships + survivor_ships

        if survivor_ships > current_ships:
            return survivor_owner, survivor_ships - current_ships
        if survivor_ships == current_ships:
            return -1, 0
        return current_owner, current_ships - survivor_ships

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
                    fleet_forces = {}
                    for _, f_owner, f_ships in fleets_this_step:
                        fleet_forces[f_owner] = fleet_forces.get(f_owner, 0) + f_ships
                    current_owner, current_ships = self.resolve_combat(current_owner, current_ships, fleet_forces)
                    
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
                fleet_forces = {}
                for _, f_owner, f_ships in fleets_this_step:
                    fleet_forces[f_owner] = fleet_forces.get(f_owner, 0) + f_ships
                current_owner, current_ships = self.resolve_combat(current_owner, current_ships, fleet_forces)

            if current_owner != -1:
                current_ships += prod

        return current_owner, current_ships

    def is_path_clear(self, from_id, to_id, travel_time, ships, angle_offset=0.0):
        """Check route against sun and intermediate planet interception."""
        from_planet = self.planet_by_id.get(from_id)
        to_planet = self.planet_by_id.get(to_id)
        if from_planet is None or to_planet is None:
            return False

        target_pos = self.predict_planet_pos(to_id, self.step + travel_time)
        src_pos = self.predict_planet_pos(from_id, self.step) or (from_planet.x, from_planet.y)
        if target_pos is None:
            return False

        base_angle = math.atan2(target_pos[1] - src_pos[1], target_pos[0] - src_pos[0])
        angle = base_angle + angle_offset
        speed = estimate_fleet_speed(ships)
        fx, fy = self.launch_pos(from_id, angle, self.step)

        for dt in range(1, travel_time + 1):
            old_fx, old_fy = fx, fy
            fx += math.cos(angle) * speed
            fy += math.sin(angle) * speed
            new_fx, new_fy = fx, fy

            if not (0 <= new_fx <= BOARD_SIZE and 0 <= new_fy <= BOARD_SIZE):
                return False

            if point_to_segment_distance((CENTER, CENTER), (old_fx, old_fy), (new_fx, new_fy)) < SUN_RADIUS + 0.1:
                return False

            for planet in self.planets:
                if planet.id == from_id:
                    continue
                if planet.id == to_id and dt >= travel_time:
                    continue
                p_old = self.predict_planet_pos(planet.id, self.step + dt - 1)
                p_new = self.predict_planet_pos(planet.id, self.step + dt)
                if p_old is None or p_new is None:
                    continue
                if swept_pair_hit((old_fx, old_fy), (new_fx, new_fy), p_old, p_new, planet.radius):
                    return False

        return True

    def find_clear_angle(self, from_id, to_id, travel_time, ships):
        """Try base angle only since fleets travel in a straight line forever and cannot steer."""
        for offset in [0.0]:
            if self.is_path_clear(from_id, to_id, travel_time, ships, angle_offset=offset):
                target_pos = self.predict_planet_pos(to_id, self.step + travel_time)
                src_pos = self.predict_planet_pos(from_id, self.step) or (
                    self.planet_by_id[from_id].x, self.planet_by_id[from_id].y
                )
                if target_pos is None:
                    return None
                base = math.atan2(target_pos[1] - src_pos[1], target_pos[0] - src_pos[0])
                return base + offset
        return None

    def target_roi(self, target, opt_t):
        """FIX 4: ROI based on income-per-turn, not penalised by ship count.
        Previously divided by opt_ships which made large attacks score poorly,
        causing the agent to ignore strong enemy planets in favour of weak neutrals.
        """
        if target.owner not in (-1, self.player):
            # Enemy planet: capturing denies their production AND adds ours
            value = target.production * 5
        elif target.production >= 4:
            value = target.production * 3
        else:
            value = float(target.production)

        # Value per turn of travel time — faster capture = higher ROI
        return value / max(1, opt_t)


def agent(obs):
    state = GameState(obs)
    arrivals = state.analyze_active_fleets()
    state.precompute_garrison_timelines(arrivals, horizon=65)

    my_planets = [p for p in state.planets if p.owner == state.player]
    if not my_planets:
        return []

    moves = []

    # --- 1. DEFENSE ---
    # FIX 5: Extended lookahead from 25 to 60 steps to catch slow approaching fleets
    defense_needs = {}
    for mine in my_planets:
        for dt in range(1, 60):
            future_owner, future_ships = state.simulate_future_garrison(mine.id, state.step + dt, arrivals)
            if future_owner != state.player:
                defense_needs[mine.id] = (future_ships + 1, state.step + dt)
                break

    available_ships = {}
    for mine in my_planets:
        if mine.id in defense_needs:
            needed, _ = defense_needs[mine.id]
            available_ships[mine.id] = max(0, mine.ships - needed - state.effective_reserve)
        else:
            available_ships[mine.id] = max(0, mine.ships - state.effective_reserve)

    for def_id, (needed_ships, limit_step) in sorted(defense_needs.items(), key=lambda x: x[1][1]):
        target_planet = state.planet_by_id[def_id]
        sorted_mine = sorted(
            my_planets,
            key=lambda p: (
                -available_ships.get(p.id, 0),
                math.hypot(p.x - target_planet.x, p.y - target_planet.y),
            ),
        )
        for mine in sorted_mine:
            if mine.id == def_id or available_ships.get(mine.id, 0) <= 0:
                continue
            send = min(available_ships[mine.id], needed_ships)
            if send <= 0:
                continue
            travel_time = state.estimate_travel_time(mine.id, def_id, send)
            if state.step + travel_time <= limit_step:
                angle = state.find_clear_angle(mine.id, def_id, travel_time, send)
                if angle is None:
                    continue
                moves.append([mine.id, angle, send])
                available_ships[mine.id] -= send
                needed_ships -= send
                if needed_ships <= 0:
                    break

    # --- 2. OFFENSE ---
    targets = [p for p in state.planets if p.owner != state.player]
    attack_options = []

    # FIX 3: extra_arrivals_map tracks fleets committed this turn so garrison
    # simulation knows about them and won't overkill the same target repeatedly.
    extra_arrivals_map = {p.id: [] for p in state.planets}

    for mine in my_planets:
        ships_avail = available_ships.get(mine.id, 0)
        if ships_avail <= 0:
            continue

        for target in targets:
            if target.id in state.comet_ids:
                if target.id not in state.comet_paths:
                    continue
                path, path_idx = state.comet_paths[target.id]
                steps_left = len(path) - path_idx
                est_t = state.estimate_travel_time(mine.id, target.id, ships_avail)
                if steps_left < est_t + 5:
                    continue

            opt_t = None
            opt_ships = None

            for dt in range(1, 45):
                # FIX 3: include already-committed fleets in garrison simulation
                future_owner, future_ships = state.simulate_future_garrison(
                    target.id, state.step + dt, arrivals,
                    extra_arrivals=extra_arrivals_map.get(target.id)
                )
                if future_owner == state.player:
                    break

                exact_need = future_ships + 1

                if target.owner == -1:
                    ships_needed = exact_need
                else:
                    ships_needed = min(ships_avail, max(exact_need, min(MIN_ATTACK_BATCH, ships_avail)))

                if exact_need > ships_avail:
                    continue

                act_t = state.estimate_travel_time(mine.id, target.id, ships_needed)
                if act_t <= dt:
                    opt_t = act_t
                    opt_ships = ships_needed
                    break

            if opt_ships is not None:
                angle = state.find_clear_angle(mine.id, target.id, opt_t, opt_ships)
                if angle is not None:
                    # FIX 4: ROI no longer divided by ship count
                    roi = state.target_roi(target, opt_t)
                    attack_options.append(
                        {
                            "from_id": mine.id,
                            "to_id": target.id,
                            "ships": opt_ships,
                            "travel_time": opt_t,
                            "roi": roi,
                            "angle": angle,
                        }
                    )

    attack_options.sort(key=lambda x: x["roi"], reverse=True)

    committed_to_target = {}

    for opt in attack_options:
        from_id = opt["from_id"]
        to_id = opt["to_id"]
        ships = opt["ships"]
        travel_time = opt["travel_time"]
        angle = opt["angle"]

        if available_ships.get(from_id, 0) < ships:
            continue

        already_committed = committed_to_target.get(to_id, 0)
        # FIX 3: use extra_arrivals_map so simulation is accurate
        future_owner, future_ships = state.simulate_future_garrison(
            to_id, state.step + travel_time, arrivals,
            extra_arrivals=extra_arrivals_map.get(to_id)
        )
        if future_owner == state.player:
            continue
        total_needed = future_ships + 1
        if already_committed >= total_needed:
            continue

        moves.append([from_id, angle, ships])
        available_ships[from_id] -= ships
        committed_to_target[to_id] = already_committed + ships

        # FIX 3: register this fleet in extra_arrivals_map so future iterations
        # in this same turn see it when simulating the garrison
        arrival_step = state.step + travel_time
        extra_arrivals_map[to_id].append((arrival_step, state.player, ships))

    # --- 3. CONSOLIDATION (backline -> frontline) ---
    enemy_planets = [p for p in state.planets if p.owner not in (-1, state.player)]
    if enemy_planets:
        for mine in my_planets:
            ships_left = available_ships.get(mine.id, 0)
            if ships_left <= state.effective_reserve:
                continue

            mine_min_enemy_dist = min(math.hypot(mine.x - e.x, mine.y - e.y) for e in enemy_planets)

            if mine_min_enemy_dist <= 15.0:
                continue

            guard_garrison = 12 if mine_min_enemy_dist < 25.0 else 8
            if state.endgame:
                guard_garrison = 0
            if ships_left <= guard_garrison:
                continue

            surplus = ships_left - guard_garrison
            candidates = []
            for dest in my_planets:
                if dest.id == mine.id:
                    continue
                dest_min_enemy_dist = min(math.hypot(dest.x - e.x, dest.y - e.y) for e in enemy_planets)
                if mine_min_enemy_dist - dest_min_enemy_dist > 7.0:
                    candidates.append((dest, dest_min_enemy_dist))

            if not candidates:
                continue

            candidates.sort(key=lambda x: x[1])
            best_dest = candidates[0][0]
            travel_time = state.estimate_travel_time(mine.id, best_dest.id, surplus)
            if travel_time >= 40:
                continue

            angle = state.find_clear_angle(mine.id, best_dest.id, travel_time, surplus)
            if angle is None:
                continue

            future_owner, _ = state.simulate_future_garrison(best_dest.id, state.step + travel_time, arrivals)
            if future_owner != state.player:
                continue

            moves.append([mine.id, angle, surplus])
            available_ships[mine.id] -= surplus

    # --- 4. ENDGAME BLITZ ---
    if state.endgame and enemy_planets:
        for mine in my_planets:
            leftover = available_ships.get(mine.id, 0)
            if leftover < MIN_ATTACK_BATCH:
                continue

            # FIX 8: try multiple enemy targets if nearest path is blocked
            sorted_enemies = sorted(
                enemy_planets,
                key=lambda e: math.hypot(mine.x - e.x, mine.y - e.y),
            )
            for nearest_enemy in sorted_enemies[:3]:
                travel_time = state.estimate_travel_time(mine.id, nearest_enemy.id, leftover)
                if travel_time >= 999:
                    continue
                angle = state.find_clear_angle(mine.id, nearest_enemy.id, travel_time, leftover)
                if angle is None:
                    continue
                moves.append([mine.id, angle, leftover])
                available_ships[mine.id] = 0
                break

    return moves