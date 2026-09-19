-- target-blocks.lua -- a passage for some editions, and the title block
-- switch. Runs at render time, once per target, with TARGET_NAME set to
-- the target's name and TITLE_BLOCK to "on" or "off".
--
-- A Div or Span with a targets attribute names the targets it is for:
--   ::: {targets="epub print"}   kept for epub and print, dropped elsewhere
--   ::: {targets="!epub"}        kept for every target but epub
-- A kept passage is unwrapped; the attribute never reaches the output.
--
-- Copyright 2026 Robert Szarka
--
-- This program is free software: you can redistribute it and/or modify
-- it under the terms of the GNU General Public License as published by
-- the Free Software Foundation, either version 3 of the License, or
-- any later version.
--
-- This program is distributed in the hope that it will be useful,
-- but WITHOUT ANY WARRANTY; without even the implied warranty of
-- MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
-- GNU General Public License for more details.
--
-- You should have received a copy of the GNU General Public License
-- along with this program.  If not, see <https://www.gnu.org/licenses/>.

local TARGET = os.getenv('TARGET_NAME') or ''
local TITLE_BLOCK = (os.getenv('TITLE_BLOCK') or 'on') ~= 'off'

local function wanted(spec)
  -- Names keep; "!name" excludes. A list of only exclusions keeps by
  -- default; a list with any plain name keeps only those.
  local keep, any_plain = nil, false
  for word in spec:gmatch('%S+') do
    if word:sub(1, 1) == '!' then
      if word:sub(2) == TARGET then return false end
    else
      any_plain = true
      if word == TARGET then keep = true end
    end
  end
  if any_plain then return keep == true end
  return true
end

local function resolve(el)
  local spec = el.attributes['targets']
  if spec == nil then return nil end
  if not wanted(spec) then return {} end
  return el.content
end

local function drop_title_block(meta)
  if TITLE_BLOCK then return meta end
  for _, key in ipairs({ 'subtitle', 'date', 'abstract', 'include-before',
                         'include-after' }) do
    meta[key] = nil
  end
  return meta
end

return {
  { Div = resolve, Span = resolve },
  { Meta = drop_title_block },
}
