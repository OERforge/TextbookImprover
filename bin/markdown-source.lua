-- markdown-source.lua -- a filtered page, written back as source.
--
-- Runs on a filtered intermediate when a target's format is markdown.
-- Markdown holds what the author decided; the filter holds what follows
-- from it. So what the filter derived on the way to HTML is taken out
-- again here (the scroll wrapper, scope on header cells, aria-hidden,
-- its bookkeeping attributes), and what it decided from a sidecar, a
-- pre-pass, or a marker is written as markup that reads back to the
-- same decision: the table-header marker, {.decorative} on an image,
-- an anchor as an empty span. Read this file again and the filter puts
-- everything else back.
--
-- TABLE_MARKERS: "class=value,..." as the filter reads it; the class
-- whose value matches a table's headers is the one written.
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

local MARKERS = {}          -- value -> class, the reverse of the filter's
for pair in (os.getenv('TABLE_MARKERS') or 'matrix=both,row-headers=first-column')
    :gmatch('[^,]+') do
  local class, value = pair:match('^%s*([^=%s]+)%s*=%s*(%S+)%s*$')
  if class and MARKERS[value] == nil then MARKERS[value] = class end
end

-- Metadata the pipeline wrote, which the next read recomputes.
local PIPELINE_META = { 'source-page', 'source-title', 'page-part',
                        'page-position', 'page-parents', 'page-role',
                        'header-includes' }

local BOOKKEEPING = { 'data-th-index', 'data-cc-ordinal', 'data-th-marker' }

local function strip_bookkeeping(attr)
  for _, key in ipairs(BOOKKEEPING) do attr.attributes[key] = nil end
end

local function headers_of(tbl)
  local row = #tbl.head.rows > 0
  local column = false
  for _, body in ipairs(tbl.bodies) do
    if body.row_head_columns > 0 then column = true end
  end
  if row and column then return 'both' end
  if column then return 'first-column' end
  if row then return 'first-row' end
  return 'none'
end

-- The column widths Word gave a table, as text for a widths attribute,
-- and the table with its widths cleared so Pandoc writes a pipe table.
-- Grid-table dashes round a width to a character and drift by one on
-- every write; an attribute keeps the number.
local function take_widths(tbl)
  local out, any = {}, false
  for i, spec in ipairs(tbl.colspecs) do
    local width = spec[2]
    if type(width) == 'number' and width > 0 then
      any = true
      out[i] = string.format('%.4f', width):gsub('0+$', ''):gsub('%.$', '')
    else
      out[i] = '0'
    end
  end
  if not any then return nil end
  local specs = {}
  for i, spec in ipairs(tbl.colspecs) do specs[i] = { spec[1], 'ColWidthDefault' } end
  tbl.colspecs = specs
  return table.concat(out, ' ')
end

local function clean_table(tbl)
  strip_bookkeeping(tbl.attr)
  local function clean_cells(rows)
    for _, row in ipairs(rows) do
      for _, cell in ipairs(row.cells) do
        cell.attr.attributes['scope'] = nil
      end
    end
  end
  clean_cells(tbl.head.rows)
  for _, body in ipairs(tbl.bodies) do
    clean_cells(body.head)
    clean_cells(body.body)
  end
  return tbl
end

function Div(div)
  -- The scroll region around a data table: derived, so unwrapped. The
  -- table inside carries the declaration as a marker div, if it needs
  -- one: a header column is not something a pipe table can say.
  if div.classes:includes('table-wrapper') then
    local out = pandoc.List({})
    for _, block in ipairs(div.content) do
      if block.t == 'Table' then
        local headers = headers_of(block)
        local column = false
        for _, body in ipairs(block.bodies) do
          if body.row_head_columns > 0 then
            column = true
            body.row_head_columns = 0
          end
        end
        block = clean_table(block)
        -- A header column needs a marker; which one depends on whether
        -- there is a header row too. With no class for the exact case,
        -- the table is written without one and reported.
        local class = column and MARKERS[headers]
        if column and not class then
          io.stderr:write(('markdown-source: no marker class for %s; '
            .. 'the table is written without its header column\n')
            :format(headers))
        end
        -- The widths go on the same div, so a pipe table can carry them.
        local widths = block.t == 'Table' and take_widths(block) or nil
        if class or widths then
          local attr = pandoc.Attr('', class and { class } or {},
                                   widths and { widths = widths } or {})
          out:insert(pandoc.Div({ block }, attr))
        else
          out:insert(block)
        end
      else
        out:insert(block)
      end
    end
    return out
  end
  -- A div with nothing left on it -- the reader took its widths and
  -- kept the box -- is unwrapped rather than written as "::: {}".
  local empty = div.identifier == '' and #div.classes == 0
  for _ in pairs(div.attributes) do empty = false end
  if empty then
    return div.content
  end
  -- A marker div the source already had, now holding the one this pass
  -- made: one is enough.
  for value, class in pairs(MARKERS) do
    if div.classes:includes(class) and #div.content == 1
        and div.content[1].t == 'Div'
        and div.content[1].classes:includes(class) then
      return div.content[1]
    end
  end
  -- An anchor the filter or the split placed as an empty div: an empty
  -- span reads back to the same id.
  if #div.content == 0 and div.identifier ~= '' then
    return pandoc.Plain({ pandoc.Span({}, pandoc.Attr(div.identifier)) })
  end
  return nil
end

local function has_spans(tbl)
  local function check(rows)
    for _, row in ipairs(rows) do
      for _, cell in ipairs(row.cells) do
        if cell.col_span > 1 or cell.row_span > 1 then return true end
      end
    end
    return false
  end
  if check(tbl.head.rows) then return true end
  for _, body in ipairs(tbl.bodies) do
    if check(body.head) or check(body.body) then return true end
  end
  return false
end

function Table(tbl)
  tbl = clean_table(tbl)
  -- Pandoc's Markdown has no cell spans, and its writer drops them
  -- silently. A merged-cell table is written as HTML instead, which the
  -- reading filter turns back into a table, spans and all.
  if has_spans(tbl) then
    return pandoc.RawBlock('html',
      pandoc.write(pandoc.Pandoc({ tbl }), 'html',
                   { html_math_method = 'mathml' }))
  end
  return tbl
end

function Image(img)
  if img.attributes['aria-hidden'] == 'true' then
    img.attributes['aria-hidden'] = nil
    img.attributes.alt = nil
    img.caption = pandoc.Inlines({})
    if not img.classes:includes('decorative') then
      img.classes:insert('decorative')
    end
  end
  img.attributes.alt = nil       -- the caption is the alt in Markdown
  return img
end

local function not_a_figure(block)
  -- A paragraph that is only an image would read back as a figure. The
  -- mark for "not a figure" is an empty span of class inline after it,
  -- ![alt](x.png)[]{.inline}, which the reading filter takes off again.
  -- (Pandoc's own mark, a non-breaking space, turns into a hard line
  -- break when a grid cell wraps at it.) A tight list item holds a
  -- Plain, which reads back loose, so it gets the mark too.
  local c = pandoc.List(block.content)
  while #c > 0 and c[1].t == 'Space' do c:remove(1) end       -- Word noise
  while #c > 0 and c[#c].t == 'Space' do c:remove(#c) end
  if #c == 1 and c[1].t == 'Image' then
    block.content = { c[1], pandoc.Span({}, pandoc.Attr('', { 'inline' })) }
    return block
  end
  return nil
end

function Para(para) return not_a_figure(para) end
function Plain(plain) return not_a_figure(plain) end

function Math(m)
  -- Word's equation export ends some equations with a thin space, "\\ ".
  -- Markdown's closing $ may not follow a space, so "$...\\ $" would not
  -- be math at all on the next read. The thin space goes.
  local text = m.text:gsub('%s*\\%s+$', ''):gsub('%s+$', '')
  if text ~= m.text then
    return pandoc.Math(m.mathtype, text)
  end
  return nil
end

function Header(h)
  -- Word leaves a trailing space on a heading; Markdown does not keep
  -- one, so the first write would differ from the second.
  while #h.content > 0 and h.content[#h.content].t == 'Space' do
    h.content:remove(#h.content)
  end
  return h
end

function Meta(meta)
  -- The author the filter moved into a <meta> in header-includes goes
  -- back to the metadata, where the next read finds it.
  if meta.author == nil and meta['header-includes'] ~= nil then
    local text = pandoc.utils.stringify(meta['header-includes'])
    local raw = pandoc.write(pandoc.Pandoc({}, pandoc.Meta({
      ['header-includes'] = meta['header-includes'] })), 'html')
    local author = (text .. raw):match('<meta name="author" content="([^"]*)"')
    if author and author ~= '' then
      meta.author = pandoc.MetaString(author)
    end
  end
  for _, key in ipairs(PIPELINE_META) do meta[key] = nil end
  return meta
end
