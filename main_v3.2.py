import math
from kaggle_environments.envs.orbit_wars.orbit_wars import (
    Planet,
    Fleet,
    CENTER,
    ROTATION_RADIUS_LIMIT,
)

# Engine defaults from Orbit Wars rules
BOARD_SIZE = 100.0
SUN_RADIUS = 10.0
MAX_FLEET_SPEED = 6.0
GAME_LENGTH = 500

# Dynamic — loosened in endgame
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

        # FIX 5: Endgame flag — ignore reserves, be fully aggressive
        self.turns_left = GAME_LENGTH - self.step
        self.endgame = self.turns_left < 100

        # Effective reserve based on game phase. 0 in early game (first 130 steps) for rapid expansion.
        self.effective_reserve = 0 if (self.step < 130 or self.endgame) else MIN_RESERVE

    def predict_planet_pos(self, planet_id, step):
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

        # Search up to 200 steps to accommodate larger 4-player maps
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
        """Predict the planet and absolute step each existing fleet will hit."""
        arrivals = {p.id: [] for p in self.planets}

        for fleet in self.fleets:
            speed = estimate_fleet_speed(fleet.ships)
            fx, fy = fleet.x, fleet.y
            angle = fleet.angle

            for dt in range(1, 120):
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

    def simulate_future_garrison(self, planet_id, target_step, arrivals_map, extra_arrivals=None):
        """Predict owner and ships at target_step, applying combat before production."""
        planet = self.planet_by_id.get(planet_id)
        if planet is None:
            return -1, 0

        current_owner = planet.owner
        current_ships = planet.ships
        prod = planet.production
        incoming = list(arrivals_map.get(planet_id, []))
        if extra_arrivals:
            incoming.extend(extra_arrivals)

        for step in range(self.step + 1, target_step + 1):
            if planet_id in self.comet_ids and self.predict_planet_pos(planet_id, step) is None:
                return -1, 0

            # 1. Combat resolution (before production)
            fleets_this_step = [f for f in incoming if f[0] == step]
            if fleets_this_step:
                fleet_forces = {}
                for _, f_owner, f_ships in fleets_this_step:
                    fleet_forces[f_owner] = fleet_forces.get(f_owner, 0) + f_ships
                current_owner, current_ships = self.resolve_combat(current_owner, current_ships, fleet_forces)

            # 2. Production (after combat)
            if current_owner != -1:
                current_ships += prod

        return current_owner, current_ships

    def is_path_clear(self, from_id, to_id, travel_time, ships, angle_offset=0.0):
        """Check route against sun and intermediate planet interception.
        FIX 6: Supports angle_offset for alternate route attempts.
        """
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
        """Try base angle first (must be 0.0 since fleets fly in straight lines)."""
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

    def target_roi(self, target, opt_ships, opt_t):
        """FIX 1: Smarter ROI — enemy planets valued much higher than neutral."""
        if target.owner not in (-1, self.player):
            # Enemy planet: high value — captures their production AND denies them
            value = target.production * 5
        elif target.production >= 4:
            # High-production neutral
            value = target.production * 3
        else:
            value = float(target.production)

        # Slight bonus for proximity (faster = better cash flow)
        proximity_bonus = 1.0 / max(1, opt_t)
        return (value + proximity_bonus) / max(1, opt_ships)


def agent(obs):
    state = GameState(obs)
    arrivals = state.analyze_active_fleets()

    my_planets = [p for p in state.planets if p.owner == state.player]
    if not my_planets:
        return []

    moves = []

    # --- 1. DEFENSE ---
    defense_needs = {}
    for mine in my_planets:
        for dt in range(1, 25):
            future_owner, future_ships = state.simulate_future_garrison(mine.id, state.step + dt, arrivals)
            if future_owner != state.player:
                defense_needs[mine.id] = (future_ships + 1, state.step + dt)
                break

    # FIX 5 (endgame): ignore reserves; FIX 3: pick senders by surplus, not just distance
    available_ships = {}
    for mine in my_planets:
        if mine.id in defense_needs:
            needed, _ = defense_needs[mine.id]
            available_ships[mine.id] = max(0, mine.ships - needed - state.effective_reserve)
        else:
            available_ships[mine.id] = max(0, mine.ships - state.effective_reserve)

    # FIX 3: Sort defense senders by surplus (most ships first), then distance
    for def_id, (needed_ships, limit_step) in sorted(defense_needs.items(), key=lambda x: x[1][1]):
        target_planet = state.planet_by_id[def_id]
        # Sort by surplus descending, then distance ascending
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

    # FIX 2: Track committed ships per target to allow multi-source attacks
    committed_to_target = {}  # to_id -> ships committed this turn

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
                future_owner, future_ships = state.simulate_future_garrison(target.id, state.step + dt, arrivals)
                if future_owner == state.player:
                    break

                # FIX 2: Account for ships already committed to this target
                already_committed = committed_to_target.get(target.id, 0)
                effective_garrison = max(0, future_ships + 1 - already_committed)
                if effective_garrison <= 0:
                    # Target already covered by committed fleets
                    break

                exact_need = effective_garrison
                if target.owner == -1:
                    # Neutral planet: attack with exactly what's needed for maximum speed and efficiency
                    ships_needed = exact_need
                else:
                    # Enemy planet: send at least MIN_ATTACK_BATCH if available to ensure takeover
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
                    # FIX 1: Better ROI formula
                    roi = state.target_roi(target, opt_ships, opt_t)
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

    for opt in attack_options:
        from_id = opt["from_id"]
        to_id = opt["to_id"]
        ships = opt["ships"]
        travel_time = opt["travel_time"]
        angle = opt["angle"]

        if available_ships.get(from_id, 0) < ships:
            continue

        # FIX 2: Allow multiple sources to attack same target if still needed
        already_committed = committed_to_target.get(to_id, 0)
        target_planet = state.planet_by_id[to_id]
        future_owner, future_ships = state.simulate_future_garrison(to_id, state.step + travel_time, arrivals)
        if future_owner == state.player:
            continue  # Already ours by then
        total_needed = future_ships + 1
        if already_committed >= total_needed:
            continue  # Already sending enough

        moves.append([from_id, angle, ships])
        available_ships[from_id] -= ships
        committed_to_target[to_id] = already_committed + ships

    # --- 3. CONSOLIDATION (backline -> frontline) ---
    enemy_planets = [p for p in state.planets if p.owner not in (-1, state.player)]
    if enemy_planets:
        for mine in my_planets:
            ships_left = available_ships.get(mine.id, 0)
            if ships_left <= state.effective_reserve:
                continue

            mine_min_enemy_dist = min(math.hypot(mine.x - e.x, mine.y - e.y) for e in enemy_planets)

            # FIX 4: Lowered threshold from 20 to 15 for more aggressive reinforcement
            if mine_min_enemy_dist <= 15.0:
                continue

            guard_garrison = 12 if mine_min_enemy_dist < 25.0 else 8
            if state.endgame:
                guard_garrison = 0  # FIX 5: endgame — send everything
            if ships_left <= guard_garrison:
                continue

            surplus = ships_left - guard_garrison
            candidates = []
            for dest in my_planets:
                if dest.id == mine.id:
                    continue
                dest_min_enemy_dist = min(math.hypot(dest.x - e.x, dest.y - e.y) for e in enemy_planets)
                # FIX 4: Lowered gap requirement from 10 to 7
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
    # FIX 5: In last 100 turns, dump all remaining ships at nearest enemy
    if state.endgame and enemy_planets:
        for mine in my_planets:
            leftover = available_ships.get(mine.id, 0)
            if leftover < MIN_ATTACK_BATCH:
                continue
            # Find nearest enemy planet
            nearest_enemy = min(
                enemy_planets,
                key=lambda e: math.hypot(mine.x - e.x, mine.y - e.y),
            )
            travel_time = state.estimate_travel_time(mine.id, nearest_enemy.id, leftover)
            if travel_time >= 999:
                continue
            angle = state.find_clear_angle(mine.id, nearest_enemy.id, travel_time, leftover)
            if angle is None:
                continue
            moves.append([mine.id, angle, leftover])
            available_ships[mine.id] = 0

    return moves