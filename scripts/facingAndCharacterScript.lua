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

-- returns facing ("right"/"left") and side ("left"/"right" of the opponent), or "", "" if unavailable
local function get_facing(player_index)
    local ok, facing, side = pcall(function()
        local gBattle = sdk.find_type_definition("gBattle")
        local sPlayer = gBattle:get_field("Player"):get_data(nil)
        local p = sPlayer.mcPlayer[player_index - 1]
        if not p then return "", "" end
        local rl = p:get_field("rl_dir")
        local cs = p:get_field("cmd_side")
        return (rl and "right" or "left"), (cs and "left" or "right")
    end)
    if not ok then return "", "" end
    return facing, side
end

local last = ""

re.on_frame(function()
    local _, name = get_character(1)
    name = name or ""

    local facing, side = "", ""
    if name ~= "" then
        facing, side = get_facing(1)
    end

    local snapshot = name .. "|" .. facing .. "|" .. side
    if snapshot ~= last then
        last = snapshot
        json.dump_file("p1_character.json", {
            p1_name = name,
            p1_facing = facing,  -- direction the character is facing
            p1_side = side,      -- which side of the opponent P1 is on
        })
    end
end)

re.on_draw_ui(function()
    local _, n1 = get_character(1)
    local facing, side = get_facing(1)
    imgui.text("P1: " .. (n1 or "N/A"))
    imgui.text("Facing: " .. facing .. "  Side: " .. side)
end)