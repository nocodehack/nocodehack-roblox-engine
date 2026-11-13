-- rbx_set_export.luau: paste into Roblox Studio (Edit) via MCP execute_luau. First insert the model with the MCP insert_asset tool
-- (parentPath game.Workspace.SetImport, assetName imp_<id>; InsertService:LoadAsset is "not authorized" for other creators' models).
-- This script serializes every workspace.SetImport.imp_* model, prints JSON lines "RBXSET|<id>|<chunk>|[parts]" (<= 800 chars each) and
-- "RBXSET|<id>|END|{name,stats}", and leaves the copy in place; then run rbx_set_meshes.luau (cache time windows for MeshPart/SpecialMesh assets) which destroys it. Read the lines from the newest Studio log:
-- python tools/rbx_set_import.py fetch. Never saves/publishes.
local HS = game:GetService("HttpService")
local folder = workspace:FindFirstChild("SetImport")
local res = {}
for _, m in ipairs(folder:GetChildren()) do
if m.Name:sub(1, 4) == "imp_" then
local ID = m.Name:sub(5)
local function c3(c) return {math.floor(c.R * 255 + .5), math.floor(c.G * 255 + .5), math.floor(c.B * 255 + .5)} end
local r4 = function(x) return math.round(x * 10000) / 10000 end
local function r4s(t) local o = {} for i, x in ipairs(t) do o[i] = r4(x) end return o end
local stats, buf, blen, chunk = {parts = 0, mesh = 0, union = 0, decal = 0, lights = 0, scripts = 0}, {}, 0, 0
local function flush()
  if #buf == 0 then return end
  print("RBXSET|" .. ID .. "|" .. chunk .. "|" .. HS:JSONEncode(buf)); buf = {}; blen = 0; chunk += 1; task.wait()
end
local function rec(p, g, gn)
  local r = {g = g, gn = gn, n = p.Name, c = p.ClassName, cf = r4s({p.CFrame:GetComponents()}), sz = r4s({p.Size.X, p.Size.Y, p.Size.Z}),
    col = c3(p.Color), mat = p.Material.Name, tr = p.Transparency, rf = p.Reflectance, cc = p.CanCollide}
  local d = {}
  for _, k in ipairs(p:GetChildren()) do
    if k:IsA("SpecialMesh") then r.sm = {t = k.MeshType.Name, id = k.MeshId, tex = k.TextureId, sc = {k.Scale.X, k.Scale.Y, k.Scale.Z}, off = {k.Offset.X, k.Offset.Y, k.Offset.Z}}
    elseif k:IsA("Decal") or k:IsA("Texture") then
      stats.decal += 1
      table.insert(d, {c = k.ClassName, f = k.Face.Name, id = k.Texture, tr = k.Transparency, col = c3(k.Color3),
        u = k:IsA("Texture") and k.StudsPerTileU or nil, v = k:IsA("Texture") and k.StudsPerTileV or nil})
    elseif k:IsA("SurfaceAppearance") then r.sa = {col = k.ColorMap}
    elseif k:IsA("SurfaceGui") then
      for _, t in ipairs(k:GetDescendants()) do
        if (t:IsA("TextLabel") or t:IsA("TextButton")) and t.Text ~= "" then r.txt = {s = t.Text, f = k.Face.Name, col = c3(t.TextColor3)}; break end
      end
    elseif k:IsA("Light") then
      stats.lights += 1; r.lt = r.lt or {}; table.insert(r.lt, {c = k.ClassName, b = k.Brightness, rg = k.Range, col = c3(k.Color), on = k.Enabled})
    end
  end
  if #d > 0 then r.d = d end
  if p:IsA("Part") then r.shape = p.Shape.Name end
  if p:IsA("MeshPart") then stats.mesh += 1; r.mesh = {id = p.MeshId, tex = p.TextureID, ms = {p.MeshSize.X, p.MeshSize.Y, p.MeshSize.Z}} end
  if p:IsA("UnionOperation") then stats.union += 1; r.un = true end  -- AssetId is not readable: unions fall back to their bounding box
  return r
end
local nid = 0   -- every Model/Folder below the root is its own group (a chair, a desk...): solid clusters never merge across groups
local function walk(o, g, gn)
  if o:IsA("BasePart") then
    stats.parts += 1
    local r = rec(o, g, gn); local n = #HS:JSONEncode(r)
    if blen + n > 800 then flush() end
    table.insert(buf, r); blen += n + 1
  elseif o:IsA("LuaSourceContainer") then stats.scripts += 1 end
  for _, k in ipairs(o:GetChildren()) do
    if k:IsA("Model") or k:IsA("Folder") then nid += 1; walk(k, nid, k.Name) else walk(k, g, gn) end
  end
end
local root = m
while #root:GetChildren() == 1 and (root:GetChildren()[1]:IsA("Model") or root:GetChildren()[1]:IsA("Folder")) do root = root:GetChildren()[1] end
walk(root, 0, root.Name)
flush()
print("RBXSET|" .. ID .. "|END|" .. HS:JSONEncode({name = root.Name, stats = stats}))
table.insert(res, ID .. " " .. HS:JSONEncode(stats))
end
end
return table.concat(res, " ; ")
