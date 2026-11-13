-- hair_batch.luau: paste into Roblox Studio (Edit) via the MCP execute_luau tool; set IDS first.
-- Loads each hair accessory, reads what Roblox uses to place it, forces the mesh + texture download into Studio's cache and
-- prints one HAIRJSON line per id (time window + placement) to the Studio log. Then: python tools/hair_studio.py collect log
local IDS = {8036108794}
local IS, HS, CP = game:GetService("InsertService"), game:GetService("HttpService"), game:GetService("ContentProvider")
local function cf(c) return {c:GetComponents()} end
local function v3(v) return {v.X, v.Y, v.Z} end
local out = {}
for _, id in ipairs(IDS) do
  local r = {id = tostring(id), t0 = DateTime.now().UnixTimestampMillis}
  local ok, m = pcall(function() return IS:LoadAsset(id) end)
  if ok then
    local acc = m:FindFirstChildWhichIsA("Accessory", true) or m:FindFirstChildWhichIsA("Hat", true)
    local h = acc and acc:FindFirstChild("Handle")
    r.name = acc and acc.Name or m.Name
    if h then
      if h:IsA("MeshPart") then
        r.kind = "meshpart"; r.mesh_id = h.MeshId; r.tex_id = h.TextureID; r.size = v3(h.Size); r.msize = v3(h.MeshSize)
      else
        local sm = h:FindFirstChildWhichIsA("SpecialMesh")
        r.kind = "special"; r.size = v3(h.Size)
        if sm then r.mesh_id = sm.MeshId; r.tex_id = sm.TextureId; r.scale = v3(sm.Scale); r.offset = v3(sm.Offset) end
      end
      local sa = h:FindFirstChildWhichIsA("SurfaceAppearance")
      if sa then r.colormap = sa.ColorMap end
      for _, a in ipairs(h:GetChildren()) do
        if a:IsA("Attachment") then r.att = cf(a.CFrame); r.att_name = a.Name; break end
      end
      if not r.att and acc and acc:IsA("Accoutrement") then r.attach_point = cf(acc.AttachmentPoint) end
      m.Parent = workspace
      CP:PreloadAsync({h})
      task.wait(1.5)                      -- let Studio finish writing the cache files inside this id's window
    else
      r.err = "no handle"
    end
    m:Destroy()
  else
    r.err = tostring(m)
  end
  r.t1 = DateTime.now().UnixTimestampMillis
  print("HAIRJSON " .. HS:JSONEncode(r))
  table.insert(out, r.id .. (r.err and " ERR" or ""))
end
return table.concat(out, " ")
