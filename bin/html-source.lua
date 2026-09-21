--[[
html-source.lua

Runs when an HTML source is read, before anything else sees it, and
does for HTML what markdown-source.lua's reading half does for
Markdown: what the page says about itself becomes a declaration, and
what an earlier run of this pipeline derived is taken out so it can be
derived again. With it, converting a page this pipeline wrote changes
nothing, which is the test.

  - Pandoc's own title block (<header id="title-block-header">) is
    dropped, and the writer will write it again. The title is in
    <title>, which the reader puts in the metadata. The subtitle and
    the date are only in the block, as <p class="subtitle"> and
    <p class="date">, and the reader keeps no attribute of a paragraph
    (Readers/HTML.hs, pPara), so they are read out of the file itself:
    the block is Pandoc's template's and has one form.
  - A table's scroll wrapper (<div class="table-wrapper">) is unwrapped;
    the filter wraps every data table itself.
  - A table that has a header row, or whose body rows each open with a
    <th>, is declared: data-th-marker says first-row, first-column, or
    both, exactly as a ::: matrix div does for a Markdown table. The
    HTML reader works out the header column from the <th> cells when
    every row agrees (Readers/HTML/Table.hs); without a declaration the
    filter would set it back to none, because a Word table never has
    one to keep. A table with no <th> anywhere is left undeclared, and
    the run reports it like any other.

Copyright 2026 Robert Szarka

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
]]

local MARKER_ATTR = 'data-th-marker'

local function header_columns(tbl)
  local found = nil
  for _, body in ipairs(tbl.bodies) do
    if #body.body > 0 then
      local n = body.row_head_columns or 0
      if found == nil then found = n elseif found ~= n then return 0 end
    end
  end
  return found or 0
end

function Table(tbl)
  if tbl.attr.attributes[MARKER_ATTR] then return nil end
  local row = #tbl.head.rows > 0
  local column = header_columns(tbl) > 0
  local value = (row and column and 'both') or (row and 'first-row')
    or (column and 'first-column') or nil
  if value == nil then return nil end
  tbl.attr.attributes[MARKER_ATTR] = value
  return tbl
end

local function title_block_fields()
  local name = PANDOC_STATE.input_files[1]
  local handle = name and io.open(name, 'r')
  if handle == nil then return {} end
  local markup = handle:read('a')
  handle:close()
  local block = markup:match('<header id="title%-block%-header">(.-)</header>')
  if block == nil then return {} end
  local fields = {}
  for _, class in ipairs({ 'subtitle', 'date' }) do
    local inner = block:match('<p class="' .. class .. '">(.-)</p>')
    if inner then
      local blocks = pandoc.read(inner, 'html').blocks
      if blocks[1] and blocks[1].content then
        fields[class] = pandoc.MetaInlines(blocks[1].content)
      end
    end
  end
  return fields
end

function Meta(meta)
  local changed = false
  for key, value in pairs(title_block_fields()) do
    if meta[key] == nil then
      meta[key] = value
      changed = true
    end
  end
  return changed and meta or nil
end

function Div(div)
  if div.identifier == 'title-block-header' then return {} end
  if div.classes:includes('table-wrapper') and #div.content == 1
      and div.content[1].t == 'Table' then
    return div.content[1]
  end
  return nil
end
