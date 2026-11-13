-- outfit_batch.luau: paste into Roblox Studio (Edit) via MCP execute_luau; set IDS. Loads each classic Shirt/Pants, prints one OUTFITJSON line per id (kind, name, template asset url). Then: python tools/outfit_fetch.py collect
local IDS = {144076358}
local IS, HS, CP = game:GetService("InsertService"), game:GetService("HttpService"), game:GetService("ContentProvider")
local out = {}
for _, id in ipairs(IDS) do
  local r = {id = tostring(id), t0 = DateTime.now().UnixTimestampMillis}
  local ok, m = pcall(function() return IS:LoadAsset(id) end)
  if ok then
    local c = m:FindFirstChildWhichIsA("Shirt", true) or m:FindFirstChildWhichIsA("Pants", true)
    if c then
      r.kind = c:IsA("Shirt") and "shirt" or "pants"; r.name = m.Name
      r.tpl = c:IsA("Shirt") and c.ShirtTemplate or c.PantsTemplate
    else r.err = "no clothing" end
    m:Destroy()
  else r.err = tostring(m) end
  r.t1 = DateTime.now().UnixTimestampMillis
  print("OUTFITJSON " .. HS:JSONEncode(r))
  table.insert(out, r.id .. (r.err and " ERR" or ""))
end
return table.concat(out, " ")
