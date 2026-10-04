-- ─────────────────────────────────────────────────────────────────────────────
--  facingAndCharacterScript.lua
--  Writes p1_character.json every frame for Python's facing resolution.
--  Reads cv_state.json (written by run_controller.py) and renders a
--  permanent corner overlay using REFramework's draw API so it is always
--  visible during gameplay — no menu interaction required.
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Character / facing helpers ────────────────────────────────────────────────

local names = {
    [1]="Ryu", [2]="Luke", [3]="Kimberly", [4]="Chun-Li", [5]="Manon",
    [6]="Zangief", [7]="JP", [8]="Dhalsim", [9]="Cammy", [10]="Ken",
    [11]="Dee Jay", [12]="Lily", [13]="A.K.I.", [14]="Rashid", [15]="Blanka",
    [16]="Juri", [17]="Marisa", [18]="Guile", [19]="Ed", [20]="E. Honda",
    [21]="Jamie", [22]="Akuma",
}

local function get_character(player_index)
    local ok, id = pcall(function()
        local gBattle = sdk.find_type_definition("gBattle")
        local info = gBattle:get_field("Info"):get_data(nil)
        local elems = info:get_field("set_info"):get_elements()
        local e = elems[player_index]
        return e and e:get_field("PlType")
    end)
    if not ok or id == nil or id == 255 then return nil, nil end
    return id, names[id] or ("Unknown (" .. tostring(id) .. ")")
end

-- Returns facing, side, and P1 health values (health is nil if unavailable).
local function get_state(player_index)
    local ok, facing, side, vnew, vold = pcall(function()
        local gBattle = sdk.find_type_definition("gBattle")
        local sPlayer = gBattle:get_field("Player"):get_data(nil)
        local p = sPlayer.mcPlayer[player_index - 1]
        if not p then return "", "", nil, nil end
        local rl = p:get_field("rl_dir")
        local cs = p:get_field("cmd_side")
        return (rl and "right" or "left"), (cs and "left" or "right"),
               p:get_field("vital_new"), p:get_field("vital_old")
    end)
    if not ok then return "", "", nil, nil end
    return facing, side, vnew, vold
end

-- ── Colour helper ─────────────────────────────────────────────────────────────
-- REFramework draw API uses packed 0xAABBGGRR (ImGui byte order).

local function rgba(r, g, b, a)
    a = a or 255
    return (a << 24) | (b << 16) | (g << 8) | r
end

-- ── HUD layout constants ──────────────────────────────────────────────────────

local HUD_X   = 14    -- screen X of the top-left corner
local HUD_Y   = 14    -- screen Y of the top-left corner
local HUD_W   = 215   -- total panel width in pixels
local PAD     = 9     -- inner padding
local LINE_H  = 19    -- height per text row

-- Mini skeleton sub-panel
local SKEL_W  = HUD_W - PAD * 2
local SKEL_H  = 145

-- 3 text rows: title, movement, attack
local TEXT_ROWS = 3
local HUD_H = PAD + TEXT_ROWS * LINE_H + PAD + SKEL_H + PAD

-- ── HUD palette ───────────────────────────────────────────────────────────────

local C_BG      = rgba(10,  10,  16, 200)
local C_BORDER  = rgba(40,  40,  70, 255)
local C_TITLE   = rgba(225, 185,  40, 255)   -- gold
local C_LABEL   = rgba(130, 130, 130, 255)   -- mid-grey labels
local C_SEP     = rgba(50,  50,  75, 255)
local C_NO_POSE = rgba(100, 100, 100, 200)

local MOVE_COLORS = {
    up      = rgba( 60, 255,  60, 255),  -- green
    down    = rgba( 60, 220, 255, 255),  -- cyan
    forward = rgba( 60, 150, 255, 255),  -- blue
    back    = rgba(255, 140,  60, 255),  -- orange
    neutral = rgba(130, 130, 130, 255),  -- grey
}
local MOVE_LABELS = {
    up      = "[^] JUMP",
    down    = "[v] CROUCH",
    forward = "[>] FWD LEAN",
    back    = "[<] BACK LEAN",
    neutral = "[ ] NEUTRAL",
}

local ATTACK_COLORS = {
    light   = rgba(255, 255,  60, 255),  -- yellow
    medium  = rgba(255, 140,  60, 255),  -- orange
    heavy   = rgba(255,  60,  60, 255),  -- red
    special = rgba(195,  60, 255, 255),  -- purple
    none    = rgba( 90,  90,  90, 255),  -- dark grey
}
local ATTACK_LABELS = {
    light   = "(L) LIGHT",
    medium  = "(M) MEDIUM",
    heavy   = "(H) HEAVY",
    special = "(S) SPECIAL",
    none    = "--- NONE",
}

-- ── Skeleton definition ───────────────────────────────────────────────────────
-- MediaPipe landmark index pairs that form the stick figure bones.

local SKEL_BONES = {
    {0,11},{0,12},            -- head -> shoulders
    {11,12},                  -- shoulder bar
    {11,13},{13,15},          -- left  arm
    {12,14},{14,16},          -- right arm
    {11,23},{12,24},          -- torso sides
    {23,24},                  -- hip bar
    {23,25},{25,27},          -- left  leg
    {24,26},{26,28},          -- right leg
}

local C_BONE  = rgba( 80, 130, 180, 200)   -- muted steel-blue
local C_JOINT = rgba( 60, 170, 255, 255)   -- bright blue joints
local C_HEAD  = rgba(255, 220,  80, 255)   -- yellow head node

-- ── State ─────────────────────────────────────────────────────────────────────

local cv_movement  = "neutral"
local cv_attack    = "none"
local cv_landmarks = {}   -- { ["0"]={x,y}, ["11"]={x,y}, ... }

local last_snapshot = ""
local last_facing   = ""
local last_side     = ""

-- ── cv_state.json reader ──────────────────────────────────────────────────────

local function read_cv_state()
    local ok, data = pcall(json.load_file, "cv_state.json")
    if not ok or type(data) ~= "table" then return end
    cv_movement  = data.movement  or "neutral"
    cv_attack    = data.attack    or "none"
    cv_landmarks = type(data.landmarks) == "table" and data.landmarks or {}
end

-- ── Skeleton renderer ─────────────────────────────────────────────────────────

local function draw_skeleton(sx, sy, sw, sh)
    -- Faint skeleton region background
    draw.filled_rect(sx, sy, sw, sh, rgba(20, 25, 35, 120))
    draw.outline_rect(sx, sy, sw, sh, rgba(50, 55, 80, 150))

    if not cv_landmarks or not next(cv_landmarks) then
        draw.text("(no pose detected)", sx + 18, sy + sh / 2 - 8, C_NO_POSE)
        return
    end

    -- Map a landmark index to pixel coords inside the skeleton box (or nil).
    local function lm_px(idx)
        local pt = cv_landmarks[tostring(idx)]
        if not pt then return nil end
        local nx = math.max(0.0, math.min(1.0, pt[1]))
        local ny = math.max(0.0, math.min(1.0, pt[2]))
        return sx + nx * sw, sy + ny * sh
    end

    -- Draw bones first so joints render on top.
    for _, bone in ipairs(SKEL_BONES) do
        local ax, ay = lm_px(bone[1])
        local bx, by = lm_px(bone[2])
        if ax and bx then
            draw.line(ax, ay, bx, by, C_BONE, 2)
        end
    end

    -- Draw joints as 6×6 filled squares centred on each landmark.
    for idx_str, _ in pairs(cv_landmarks) do
        local px, py = lm_px(tonumber(idx_str))
        if px then
            local col = (idx_str == "0") and C_HEAD or C_JOINT
            draw.filled_rect(px - 3, py - 3, 6, 6, col)
        end
    end
end

-- ── Main HUD renderer ─────────────────────────────────────────────────────────

local function draw_hud()
    local x0 = HUD_X
    local y0 = HUD_Y

    -- Panel background + border
    draw.filled_rect(x0, y0, HUD_W, HUD_H, C_BG)
    draw.outline_rect(x0, y0, HUD_W, HUD_H, C_BORDER)

    local tx = x0 + PAD
    local ty = y0 + PAD

    -- Title
    draw.text("BodyController", tx, ty, C_TITLE)
    ty = ty + LINE_H
    draw.line(x0 + 4, ty - 3, x0 + HUD_W - 4, ty - 3, C_SEP, 1)

    -- Movement
    local mv_col   = MOVE_COLORS[cv_movement]   or MOVE_COLORS.neutral
    local mv_label = MOVE_LABELS[cv_movement]   or cv_movement
    draw.text("Move ", tx,       ty, C_LABEL)
    draw.text(mv_label, tx + 46, ty, mv_col)
    ty = ty + LINE_H

    -- Attack
    local atk_col   = ATTACK_COLORS[cv_attack]  or ATTACK_COLORS.none
    local atk_label = ATTACK_LABELS[cv_attack]  or cv_attack
    draw.text("Atk  ", tx,       ty, C_LABEL)
    draw.text(atk_label, tx + 46, ty, atk_col)
    ty = ty + PAD

    -- Mini skeleton
    draw_skeleton(tx, ty, SKEL_W, SKEL_H)
end

-- ── REFramework frame callback ────────────────────────────────────────────────

re.on_frame(function()
    -- 1. Write facing/character/health JSON when state changes.
    local _, name = get_character(1)
    name = name or ""

    local facing, side, health, health_old = "", "", nil, nil
    if name ~= "" then
        facing, side, health, health_old = get_state(1)
    end
    last_facing = facing
    last_side   = side

    local h_str = tostring(health) .. "|" .. tostring(health_old)
    local snapshot = name .. "|" .. facing .. "|" .. side .. "|" .. h_str
    if snapshot ~= last_snapshot then
        last_snapshot = snapshot
        json.dump_file("p1_character.json", {
            p1_name       = name,
            p1_facing     = facing,
            p1_side       = side,
            p1_health     = health,      -- current HP (nil before match starts)
            p1_health_old = health_old,  -- HP from previous frame
	        p1_take_damage = (p1_health ~= p1_health_old),
        })
    end

    -- 2. Poll cv_state.json written by Python.
    read_cv_state()

    -- 3. Render the permanent corner overlay.
    --    draw.* calls in re.on_frame() are always visible — no menu needed.
    draw_hud()
end)

-- ── REFramework menu panel ────────────────────────────────────────────────────

re.on_draw_ui(function()
    local _, n1 = get_character(1)
    local facing, side, health, health_old = get_state(1)
    imgui.text("P1: "        .. (n1 or "N/A"))
    imgui.text("Facing: "    .. facing .. "  Side: " .. side)
    imgui.text("P1 health: " .. tostring(health) .. "  (old " .. tostring(health_old) .. ")")
    imgui.text("P1 take_damage: " .. tostring(health ~= health_old))
    imgui.separator()
    imgui.text("Movement: "  .. cv_movement)
    imgui.text("Attack:   "  .. cv_attack)
end)