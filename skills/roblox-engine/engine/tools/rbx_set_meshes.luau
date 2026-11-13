-- rbx_set_meshes.luau: run after rbx_set_export.luau, same Studio session. For each workspace.SetImport.imp_<ID> (set ID) it preloads every
-- distinct mesh/texture, one at a time, printing "RBXMESH|<ID>|{mesh,tex,t0,t1}" so tools/rbx_set_import.py can match Studio's content-cache
-- entries to ids by time window (see tools/hair_studio.py). FROM/TO = slice of the distinct list (keep ~40 per call). DESTROY=true removes the copy.
local ID, FROM, TO, DESTROY = "14200694863", 1, 40, false
local HS, CP = game:GetService("HttpService"), game:GetService("ContentProvider")
local m = workspace.SetImport["imp_" .. ID]
local seen, list = {}, {}
for _, p in ipairs(m:GetDescendants()) do
  local mid, tex
  if p:IsA("MeshPart") then mid, tex = p.MeshId, p.TextureID
  elseif p:IsA("SpecialMesh") then mid, tex = p.MeshId, p.TextureId end
  if mid and mid ~= "" and not seen[mid .. "|" .. tex] then seen[mid .. "|" .. tex] = true; table.insert(list, {p, mid, tex}) end
end
for i = FROM, math.min(TO, #list) do
  local e = list[i]
  local t0 = DateTime.now().UnixTimestampMillis
  pcall(function() CP:PreloadAsync({e[1]}) end)
  task.wait(0.8)
  print("RBXMESH|" .. ID .. "|" .. HS:JSONEncode({mesh = e[2], tex = e[3], t0 = t0, t1 = DateTime.now().UnixTimestampMillis}))
end
if DESTROY then m:Destroy() end
return "distinct " .. #list
