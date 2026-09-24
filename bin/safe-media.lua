-- safe-media.lua -- rewrite a page's local media references to names
-- that need no percent-encoding, matching what convert.py copies beside
-- the page. See lib/names.py for the rule; the two must agree.
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

local function decode(s)
  return (s:gsub('%%(%x%x)', function(h) return string.char(tonumber(h, 16)) end))
end

local function safe_path(path)
  local parts = {}
  for part in (path .. '/'):gmatch('([^/]*)/') do
    local p = part:gsub('[^A-Za-z0-9%._%-]+', '-'):gsub('%-+%.', '.')
      :gsub('^%-+', ''):gsub('%-+$', '')
    if p == '' then p = '-' end
    parts[#parts + 1] = p
  end
  return table.concat(parts, '/')
end

local function is_local(src)
  return not (src:match('^%a[%w+.-]*:') or src:match('^//') or src:match('^#'))
end

function Image(img)
  if is_local(img.src) then
    img.src = safe_path(decode(img.src))
  end
  return img
end

-- A link to a local file that isn't a page -- a PDF, a Word file, a deck
-- of slides the page offers -- is copied beside the page as an image is,
-- so its reference takes the same safe name. A link to a page (.html)
-- is the split's and the packager's to resolve, and a link with no
-- extension isn't to a file.
function Link(link)
  if is_local(link.target) then
    local path, rest = link.target:match('^([^#?]*)(.*)$')
    if path ~= '' and path:match('%.%w+$')
        and not path:lower():match('%.x?html?$') then
      link.target = safe_path(decode(path)) .. rest
    end
  end
  return link
end
