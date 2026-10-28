
-------------------------------------------------------------------------------
-- Stilwater minimal HUD (appended to the game's hud.lua by build.py)
--
-- The health/weapon ring and the cash counter are drawn smaller and fade out
-- when nothing is happening. They come back when health, weapon, ammo, cash or
-- respect change, while aiming, sprinting, hurt or wanted, and while the weapon
-- wheel is open.
--
-- The minimap is a slightly wide rectangle (build.py redraws its round mask texture): the round
-- frame and the notoriety arcs are hidden, and the notoriety icons sit in a row
-- above the map (police) and below it (gangs).
--
-- The game fades whole HUD elements itself (cutscenes, menus) through
-- hud_element_fade(). For the two elements handled here that request is kept as
-- the element's "game alpha" and multiplied with the idle fade, so both work.
-------------------------------------------------------------------------------

Stilwater_hud = {
	scale = 0.8,         -- health/weapon ring and cash, relative to vanilla
	map_scale = 1.0,     -- minimap
	icon_scale = 0.6,    -- notoriety icons in the rows by the map
	idle_delay = 4,      -- seconds without changes before fading out
	idle_alpha = 0,      -- how visible idle elements stay (0 = hidden)
	fade_time = 0.6,     -- seconds for the idle fade

	enabled = false,
	last_time = -1,
	elements = {},       -- "HEALTH"/"CASH" -> { h, alpha, game_alpha, game_fade_time, awake_until }
	weapon = {},
}

function stilwater_hud_wake(name)
	local e = Stilwater_hud.elements[name]
	if e ~= nil then
		e.awake_until = vint_get_time_index() + Stilwater_hud.idle_delay
	end
end

function stilwater_hud_wake_all()
	for name, e in Stilwater_hud.elements do
		stilwater_hud_wake(name)
	end
end

function stilwater_hud_scale(h, k)
	local sx, sy = vint_get_property(h, "scale")
	vint_set_property(h, "scale", sx * k, sy * k)
end

function stilwater_hud_square_map()
	-- Arcs and frame only fit a round map. The game toggles the arcs' "visible" but never
	-- their alpha, so alpha keeps them hidden.
	local round = { "map_base_bottom", "map_base_top", "gang_noto_bg", "police_noto_bg",
		"gang_noto_fill_0", "gang_noto_fill_1", "police_noto_fill_0", "police_noto_fill_1" }
	for i, name in round do
		vint_set_property(vint_object_find(name), "alpha", 0)
	end

	-- The map's rectangle is the (centred) mask bitmap behind it, scaled: %MASK_SIZE% px wide and
	-- %MAP_HEIGHT% tall (build.py fills these in).
	local bg_h = vint_object_find("bg_map")
	local cx, cy = vint_get_property(bg_h, "anchor")
	local sx = vint_get_property(bg_h, "scale")
	local half = %MASK_SIZE% / 2 * sx
	local half_h = %MAP_HEIGHT% / 2 * sx
	local k = Stilwater_hud.icon_scale
	local step = 44 * k + 2
	for i = 1, 5 do
		-- level 1 on the left, rows right-aligned to the map's edge
		local x = cx + half - step * (5 - i) - step * 0.5
		local police_h = vint_object_find("police_noto_icon_" .. i)
		vint_set_property(police_h, "anchor", x, cy - half_h - step * 0.5 - 2)
		vint_set_property(police_h, "scale", k, k)
		local gang_h = vint_object_find("gang_noto_icon_" .. i)
		vint_set_property(gang_h, "anchor", x, cy + half_h + step * 0.5 + 2)
		vint_set_property(gang_h, "scale", k, k)
	end
end

function stilwater_hud_init()
	if MP_enabled == true then
		return
	end
	local s = Stilwater_hud
	local health_h = vint_object_find("health_grp")
	local cash_h = vint_object_find("cash")
	local map_h = vint_object_find("map_grp")

	-- Shrink the ring and cash as one cluster around the ring's anchor.
	local rx, ry = vint_get_property(health_h, "anchor")
	local cx, cy = vint_get_property(cash_h, "anchor")
	stilwater_hud_scale(health_h, s.scale)
	stilwater_hud_scale(cash_h, s.scale)
	vint_set_property(cash_h, "anchor", rx + (cx - rx) * s.scale, ry + (cy - ry) * s.scale)
	stilwater_hud_scale(map_h, s.map_scale)
	stilwater_hud_square_map()

	s.elements["HEALTH"] = { h = health_h, alpha = 1, game_alpha = 1, game_fade_time = .25, awake_until = 0 }
	s.elements["CASH"] = { h = cash_h, alpha = 1, game_alpha = 1, game_fade_time = .25, awake_until = 0 }
	s.enabled = true
	stilwater_hud_wake_all()
	thread_new("stilwater_hud_process")
end

function stilwater_hud_busy()
	if Hud_player_status.health_pct < 0.999 or Hud_player_status.is_sprinting == true then
		return true
	end
	if Hud_weapon_status.fine_aim_transition ~= nil and Hud_weapon_status.fine_aim_transition > 0 then
		return true
	end
	if Hud_noto_data.police.cur_level > 0 or Hud_noto_data.gangs.cur_level > 0 then
		return true
	end
	return false
end

function stilwater_hud_process()
	local s = Stilwater_hud
	while true do
		thread_yield()
		local now = vint_get_time_index()
		local dt = now - s.last_time
		if s.last_time < 0 or dt < 0 or dt > 1 then
			dt = 0
		end
		s.last_time = now

		local busy = stilwater_hud_busy()
		for name, e in s.elements do
			local target = s.idle_alpha
			local fade_time = s.fade_time
			if busy == true and name == "HEALTH" then
				target = 1
			elseif now < e.awake_until then
				target = 1
			end
			if e.game_alpha < 1 then
				-- the game is fading this element for its own reasons; follow it at its speed
				fade_time = e.game_fade_time
			end
			target = target * e.game_alpha

			if e.alpha ~= target then
				local step = 1
				if fade_time > 0 then
					step = dt / fade_time
				end
				if e.alpha < target then
					e.alpha = e.alpha + step
					if e.alpha > target then e.alpha = target end
				else
					e.alpha = e.alpha - step
					if e.alpha < target then e.alpha = target end
				end
				vint_set_property(e.h, "alpha", e.alpha)
			end
		end
	end
end

-- Game fades of the managed elements become their game alpha; everything else is unchanged.
Stilwater_vanilla_element_fade = hud_element_fade
function hud_element_fade(element_id, fade, duration)
	local name = element_id
	if type(element_id) == "number" then
		name = Hud_elements[element_id]
	end
	local e = Stilwater_hud.elements[name]
	if Stilwater_hud.enabled ~= true or e == nil then
		Stilwater_vanilla_element_fade(element_id, fade, duration)
		return
	end
	local target = 1
	if fade == 0 then
		target = 0
	elseif fade == 1 then
		target = .35
	end
	if duration == nil or duration < 0 then
		duration = .25
	end
	e.game_alpha = target
	e.game_fade_time = duration
end

Stilwater_vanilla_hud_init = hud_init
function hud_init()
	Stilwater_vanilla_hud_init()
	stilwater_hud_init()
end

Stilwater_vanilla_status_change = hud_player_status_change
function hud_player_status_change(di_h, event_name)
	local sprint_enabled, health_pct = vint_dataitem_get(di_h)
	if health_pct ~= Hud_player_status.health_pct then
		stilwater_hud_wake("HEALTH")
	end
	Stilwater_vanilla_status_change(di_h, event_name)
end

Stilwater_vanilla_status_inf_change = hud_player_status_inf_change
function hud_player_status_inf_change(di_h, event_name)
	local cash = vint_dataitem_get(di_h)
	if cash ~= nil and floor(cash) ~= Hud_player_status.cash then
		stilwater_hud_wake("CASH")
	end
	Stilwater_vanilla_status_inf_change(di_h, event_name)
end

Stilwater_vanilla_weapon_change = hud_player_weapon_change
function hud_player_weapon_change(di_h, event_name)
	local wpn_bmp_name, rdy_ammo, rsv_ammo = vint_dataitem_get(di_h)
	local w = Stilwater_hud.weapon
	if wpn_bmp_name ~= w.bmp or rdy_ammo ~= w.ammo or rsv_ammo ~= w.reserve then
		w.bmp = wpn_bmp_name
		w.ammo = rdy_ammo
		w.reserve = rsv_ammo
		stilwater_hud_wake("HEALTH")
	end
	Stilwater_vanilla_weapon_change(di_h, event_name)
end

Stilwater_vanilla_weapon_freq_change = hud_player_weapon_freq_change
function hud_player_weapon_freq_change(di_h, event_name)
	local ammo_ready = vint_dataitem_get(di_h)
	if ammo_ready ~= Stilwater_hud.weapon.ammo_ready then
		Stilwater_hud.weapon.ammo_ready = ammo_ready
		stilwater_hud_wake("HEALTH")
	end
	Stilwater_vanilla_weapon_freq_change(di_h, event_name)
end

Stilwater_vanilla_respect_change = hud_player_respect_change
function hud_player_respect_change(di_h, event_name)
	local current_respect = vint_dataitem_get(di_h)
	if current_respect ~= Hud_player_status.respect then
		stilwater_hud_wake("HEALTH")
	end
	Stilwater_vanilla_respect_change(di_h, event_name)
end

Stilwater_vanilla_inventory_show = hud_inventory_show
function hud_inventory_show()
	stilwater_hud_wake_all()
	Stilwater_vanilla_inventory_show()
end
