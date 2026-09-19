-- header-includes.lua -- add a file's contents to the document's
-- header-includes, alongside whatever is already there.
--
-- Pandoc's --include-in-header sets the header-includes *variable*, and a
-- variable set on the command line replaces the metadata field of the
-- same name rather than merging with it. So a page whose metadata carries
-- header-includes -- the author <meta> figures-and-tables.lua writes, the
-- provenance <meta> split-pages.py writes -- lost them the moment
-- convert.py added its stylesheet that way, and nothing said so. Reading
-- the file here and appending it to the metadata keeps both.
--
--   HEADER_INCLUDES_FILE   path to raw HTML to add (the stylesheet block)
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

local path = os.getenv('HEADER_INCLUDES_FILE')

function Pandoc(doc)
  if path == nil or path == '' then return doc end
  local fh = io.open(path, 'r')
  if fh == nil then
    io.stderr:write('[header-includes] cannot read ' .. path .. '\n')
    return doc
  end
  local text = fh:read('a')
  fh:close()
  local block = pandoc.MetaBlocks({ pandoc.RawBlock('html', text) })
  local existing = doc.meta['header-includes']
  local include = pandoc.MetaList({})
  if existing ~= nil then
    if existing.t == 'MetaList' then
      for _, item in ipairs(existing) do include:insert(item) end
    else
      include:insert(existing)
    end
  end
  include:insert(block)
  doc.meta['header-includes'] = include
  return doc
end
