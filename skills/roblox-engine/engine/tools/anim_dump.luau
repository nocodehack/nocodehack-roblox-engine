-- anim_dump.luau: paste into Roblox Studio (Edit) via MCP execute_luau; tools/fetch_library.py jobs fills JOBS.
-- Each job = {slug, id, name}: id is an Animation asset (KeyframeSequenceProvider) or a model already inserted at
-- workspace.AnimImport.imp_<id> (MCP insert_asset), where the KeyframeSequence/Animation called <name> is looked up.
-- Returns JSON {slug: {id, name, loop, pri, kf}} padded to ~98 000 chars so the MCP saves it to a file (keeps chat small).
-- Then: python tools/fetch_library.py collect anims <saved file>. Never saves or publishes the place.
local JOBS = {{slug = "wave", id = "128777973", name = "Wave"}}
local KSP, HS = game:GetService("KeyframeSequenceProvider"), game:GetService("HttpService")
local function r3(x) return math.floor(x * 1000 + 0.5) / 1000 end
local function seq(j)
  local holder = workspace:FindFirstChild("AnimImport")
  local m = holder and holder:FindFirstChild("imp_" .. j.id)
  if m then
    for _, d in ipairs(m:GetDescendants()) do
      if d.Name:lower() == j.name:lower() then
        if d:IsA("KeyframeSequence") then return d end
        if d:IsA("Animation") then return KSP:GetKeyframeSequenceAsync(d.AnimationId) end
      end
    end
    error("no clip named " .. j.name)
  end
  return KSP:GetKeyframeSequenceAsync("rbxassetid://" .. j.id)
end
local out = {}
for _, j in ipairs(JOBS) do
  local ok, ks = pcall(seq, j)
  if ok then
    local kf = {}
    for _, k in ipairs(ks:GetKeyframes()) do
      local p = {}
      for _, pose in ipairs(k:GetDescendants()) do
        if pose:IsA("Pose") and pose.Name ~= "HumanoidRootPart" then
          local axis, ang = pose.CFrame:ToAxisAngle()
          local e = {r = {r3(axis.X * ang), r3(axis.Y * ang), r3(axis.Z * ang)}}
          local pos = pose.CFrame.Position
          if pos.Magnitude > 1e-4 then e.p = {r3(pos.X), r3(pos.Y), r3(pos.Z)} end
          if pose.EasingStyle.Name ~= "Linear" then e.e = pose.EasingStyle.Name end
          if pose.EasingDirection.Name ~= "In" then e.d = pose.EasingDirection.Name end
          p[pose.Name] = e
        end
      end
      table.insert(kf, {t = r3(k.Time), p = p})
    end
    table.sort(kf, function(a, b) return a.t < b.t end)
    out[j.slug] = {id = tonumber(j.id), name = j.name, loop = ks.Loop, pri = ks.Priority.Name, kf = kf}
  else
    out[j.slug] = {id = tonumber(j.id), name = j.name, err = tostring(ks)}
  end
end
local s = HS:JSONEncode(out)
return s .. string.rep(" ", math.max(0, 98000 - #s))
