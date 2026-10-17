-- header-includes.lua -- add a file's contents to the document's
-- header-includes, alongside whatever is already there, and the page's
-- landmarks around its own include-before and include-after.
--
-- Pandoc's --include-in-header sets the header-includes *variable*, and a
-- variable set on the command line replaces the metadata field of the
-- same name rather than merging with it. So a page whose metadata carries
-- header-includes -- the author <meta> figures-and-tables.lua writes, the
-- provenance <meta> split-pages.py writes -- lost them the moment
-- convert.py added its stylesheet that way, and nothing said so. Reading
-- the file here and appending it to the metadata keeps both.
--
-- --include-before-body and --include-after-body are the same: a target's
-- header and footer took the place of a page's own include-before and
-- include-after, an epigraph a Markdown source gives in its metadata. So
-- what goes before the page's content (its banner, then <main>) is put
-- before the page's own include-before, and what goes after it (</main>,
-- then its footer) after its own include-after, which are inside <main>.
--
--   HEADER_INCLUDES_FILE   path to raw HTML to add (the stylesheet block)
--   INCLUDE_BEFORE_FILE    path to raw HTML to put first in include-before
--   INCLUDE_AFTER_FILE     path to raw HTML to put last in include-after
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

-- The raw HTML in the file an environment variable names, as metadata;
-- nil when it names none.
local function from_file(name)
  local path = os.getenv(name)
  if path == nil or path == '' then return nil end
  local fh = io.open(path, 'r')
  if fh == nil then
    io.stderr:write('[header-includes] cannot read ' .. path .. '\n')
    return nil
  end
  local text = fh:read('a')
  fh:close()
  return pandoc.MetaBlocks({ pandoc.RawBlock('html', text) })
end

-- A metadata field's value as a list of its items: a list's own, or the
-- one value. A metadata value has no .t in Pandoc 3; its type says what
-- it is.
local function items(value)
  local list = pandoc.MetaList({})
  if value == nil then return list end
  if pandoc.utils.type(value) == 'List' then
    for _, item in ipairs(value) do list:insert(item) end
  else
    list:insert(value)
  end
  return list
end

local function add(meta, key, block, first)
  if block == nil then return end
  local list = items(meta[key])
  if first then list:insert(1, block) else list:insert(block) end
  meta[key] = list
end

function Pandoc(doc)
  add(doc.meta, 'header-includes', from_file('HEADER_INCLUDES_FILE'), false)
  add(doc.meta, 'include-before', from_file('INCLUDE_BEFORE_FILE'), true)
  add(doc.meta, 'include-after', from_file('INCLUDE_AFTER_FILE'), false)
  return doc
end
