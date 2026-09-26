-- markdown-source.lua -- a filtered page, written back as source.
--
-- Runs on a filtered intermediate when a target's format is markdown or
-- asciidoc. For AsciiDoc, what Pandoc's writer writes and its reader
-- can't read back is written as AsciiDoc it can: the table-header marker
-- and raw HTML as blocks (an open block with a role, a passthrough block),
-- an anchor as [[id]], a decorative image with role=decorative, and
-- {empty} between a word and its footnote.
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

-- What a page loses in the writing, for the run's fidelity report
-- (fidelity.csv): convert.py names a file per page in FIDELITY_FOUND, and
-- each note on the terminal below is a row there too, its kind and a
-- detail, separated by a tab.
local FIDELITY_FILE = os.getenv('FIDELITY_FOUND')
local function lost(kind, detail)
  if not FIDELITY_FILE or FIDELITY_FILE == '' then return end
  local fh = io.open(FIDELITY_FILE, 'a')
  if fh then
    fh:write(kind .. '\t' .. (tostring(detail or ''):gsub('[\t\n]', ' ')) .. '\n')
    fh:close()
  end
end

local MARKERS = {}          -- value -> class, the reverse of the filter's
for pair in (os.getenv('TABLE_MARKERS') or 'matrix=both,row-headers=first-column')
    :gmatch('[^,]+') do
  local class, value = pair:match('^%s*([^=%s]+)%s*=%s*(%S+)%s*$')
  if class and MARKERS[value] == nil then MARKERS[value] = class end
end

-- Metadata the pipeline wrote, which the next read recomputes.
local ADOC = FORMAT:match('asciidoc') ~= nil

-- An open block with a role, written whole: the reader loses the block
-- when a blank line comes before its closing "--" after a delimited
-- block (a quotation), and the writer puts a blank line between any two
-- blocks, so the content is written here and the delimiters put around it.
local function open_block(role, blocks)
  local text = pandoc.write(pandoc.Pandoc(blocks), 'asciidoc',
                            { wrap_text = 'none' }):gsub('%s+$', '')
  return pandoc.RawBlock('asciidoc', '[.' .. role .. ']\n--\n' .. text .. '\n--\n\n')
end

local function passthrough(html)
  -- Pandoc writes a raw block as it stands, so the block ends with its own
  -- blank line; one before it would end a list item's continuation.
  return pandoc.RawBlock('asciidoc', '++++\n' .. html .. '\n++++\n\n')
end

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
          lost('header-column-dropped', headers)
          io.stderr:write(('markdown-source: no marker class for %s; '
            .. 'the table is written without its header column\n')
            :format(headers))
        end
        -- The widths go on the same div, so a pipe table can carry them.
        -- An AsciiDoc table keeps its own, in cols.
        local widths = block.t == 'Table' and not ADOC and take_widths(block) or nil
        if ADOC and class then
          -- Pandoc's AsciiDoc writer drops a div; an open block with the
          -- marker as its role reads back to the same div.
          out:insert(open_block(class, { block }))
        elseif class or widths then
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
    if ADOC then
      -- Alone on its line, [[id]] is a block anchor for whatever block
      -- follows, and an error when none does; {empty} keeps it inline.
      return pandoc.Plain({ pandoc.RawInline('asciidoc',
        '{empty}[[' .. div.identifier .. ']]') })
    end
    return pandoc.Plain({ pandoc.Span({}, pandoc.Attr(div.identifier)) })
  end
  -- A frame, which the AsciiDoc writer would reduce to the link inside:
  -- the <iframe> it came from, in a passthrough block.
  if ADOC and div.classes:includes('embed') then
    local parts = {}
    for _, pair in ipairs(div.attributes) do
      parts[#parts + 1] = ('%s="%s"'):format(pair[1],
        pair[2]:gsub('&', '&amp;'):gsub('"', '&quot;'))
    end
    return passthrough('<iframe ' .. table.concat(parts, ' ') .. '></iframe>')
  end
  -- Any other div: the writer drops it and writes its blocks with blank
  -- lines between, which inside a list item leaves the later ones outside
  -- the item. Unwrapped here, they're the item's own blocks, joined as
  -- they should be; an id goes first as an anchor, so links still land.
  if ADOC and #div.content > 0 then
    local out = pandoc.Blocks({})
    if div.identifier ~= '' then
      out:insert(pandoc.Plain({ pandoc.RawInline('asciidoc',
        '{empty}[[' .. div.identifier .. ']]') }))
    end
    out:extend(div.content)
    return out
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

local function has_row_spans(tbl)
  local function check(rows)
    for _, row in ipairs(rows) do
      for _, cell in ipairs(row.cells) do
        if cell.row_span > 1 then return true end
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

-- A table cell's formula: | separates cells, so bars in its TeX are
-- written \vert and \Vert, which render the same.
local function cell_math(tbl)
  return tbl:walk({ Math = function(m)
    if not m.text:find('|', 1, true) then return nil end
    local text = m.text:gsub('\\|', '\\Vert '):gsub('|', '\\vert ')
    return pandoc.Math(m.mathtype, text)
  end })
end

-- AsciiDoc has column spans, and its reader keeps them; a row span it
-- reads as an ordinary cell. And a table grouped into bodies (a banded
-- table, kept whole for a source target) has no AsciiDoc form: the
-- writer flattens the groups, which come back as one body. Either goes
-- as HTML, whose <tbody> groups the reader keeps. It's written in a pass
-- of its own, before the rest of this filter: the inline handlers run
-- before any block handler, and the AsciiDoc they leave in the text is
-- dropped by the HTML writer.
-- And a cell holding more than paragraphs (a listing, a list, a quotation,
-- a table), or code with a bar in it: | ends a cell even inside a listing,
-- the writer can escape a bar in text but not in code, and a listing left
-- open by the break makes the reader hang.
local CELL_BLOCKS = { Plain = true, Para = true }
local function complex_cells(tbl)
  local complex = false
  local function check(rows)
    for _, row in ipairs(rows) do
      for _, cell in ipairs(row.cells) do
        for _, block in ipairs(cell.contents) do
          if not CELL_BLOCKS[block.t] then complex = true end
        end
        pandoc.Blocks(cell.contents):walk({
          Code = function(c) if c.text:find('|', 1, true) then complex = true end end,
        })
      end
    end
  end
  check(tbl.head.rows)
  for _, body in ipairs(tbl.bodies) do check(body.head); check(body.body) end
  check(tbl.foot.rows)
  return complex
end

local function adoc_html_table(tbl)
  local grouped = #tbl.bodies > 1
  for _, body in ipairs(tbl.bodies) do
    if #body.head > 0 then grouped = true end
  end
  -- A table with a role (a layout table is role="presentation") has
  -- nowhere to keep it in AsciiDoc, and would come back a data table.
  local role = tbl.attr.attributes.role ~= nil
  if not (grouped or role or has_row_spans(tbl) or complex_cells(tbl)) then return nil end
  return passthrough(pandoc.write(pandoc.Pandoc({ clean_table(tbl) }), 'html',
                                  { html_math_method = 'mathml' }))
end

function Table(tbl)
  tbl = clean_table(tbl)
  if ADOC then return cell_math(tbl) end
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
  if ADOC then return adoc_image(img) end
  return img
end

-- An anchor: an empty span with an id, which the AsciiDoc writer writes
-- as [#id]## and its reader reads as a highlighted span of text.
function Span(span)
  if ADOC and #span.content == 0 and span.identifier ~= '' then
    return pandoc.RawInline('asciidoc', '[[' .. span.identifier .. ']]')
  end
  -- Any other span, written here in the unconstrained form, [.role]##...##:
  -- the writer's constrained #...# ends at a # inside it, such as a link's
  -- fragment, and an empty span it writes as [.role]####, which reads back
  -- as text. (Nested spans were merged in the first pass.)
  if ADOC and (#span.classes > 0 or span.identifier ~= '') then
    local attr = span.identifier ~= '' and ('#' .. span.identifier) or ''
    for _, class in ipairs(span.classes) do     -- the reader joins roles with spaces
      for part in class:gmatch('%S+') do attr = attr .. '.' .. part end
    end
    local out = pandoc.Inlines({ pandoc.RawInline('asciidoc', '[' .. attr .. ']##') })
    if #span.content == 0 then
      out:insert(pandoc.RawInline('asciidoc', '{empty}'))
    else
      out:extend(span.content)
    end
    out:insert(pandoc.RawInline('asciidoc', '##'))
    return out
  end
  if ADOC then return span.content end     -- no attributes: nothing to keep
  return nil
end

-- First pass: a span inside a span takes nothing but its classes to the
-- outer one. Nested, both would be ##...##, which is ambiguous.
local function merge_spans(span)
  local merged = false
  span.content = span.content:walk({ Span = function(inner)
    merged = true
    for _, class in ipairs(inner.classes) do
      if not span.classes:includes(class) then span.classes:insert(class) end
    end
    if inner.identifier ~= '' then
      return pandoc.Inlines({ pandoc.Span({}, pandoc.Attr(inner.identifier)) })
        .. inner.content
    end
    return inner.content
  end })
  return merged and span or nil
end

-- Text that means something at the start of an AsciiDoc line, which
-- Pandoc's writer leaves as it is: a block title (.), a heading (=), a
-- comment (//), a delimiter (----, ****, ____, ++++, three apostrophes),
-- an admonition label (NOTE:), an attribute entry (:name:), a block
-- macro (include::, image::). Read back, the line is dropped or
-- restructured, or (a leading period in a list item) the file fails.
local ADMONITIONS = { NOTE = true, TIP = true, IMPORTANT = true,
                      WARNING = true, CAUTION = true }
local function hazard_at_start(text)
  return text:match('^%.') or text:match('^=') or text:match('^//')
    or text:match('^%-%-%-%-') or text:match('^%*%*%*%*')
    or text:match('^____') or text:match('^%+%+%+%+')
    or text:match('^\39\39\39')
    or (text:match('^%u+:$') and ADMONITIONS[text:sub(1, -2)])
    or text:match('^:[%w_][%w_-]*!?:') or text:match('^[%a_][%w_-]*::%S')
    -- a link: macro's text reads as just its number when it starts with
    -- one and a period, "9.1 Null and Alternative Hypotheses" as "9"
    or text:match('^%d+%.')
end

-- A footnote right after a word is footnote:[...] joined to it, which the
-- AsciiDoc reader doesn't take for the macro; {empty} between them is
-- nothing on the page. And {empty} goes before a line's hazard, between
-- every two colons (Pandoc's reader makes a description list of any line
-- with :: in it, std::cout included, where Asciidoctor wants a space
-- after), and between the two characters of a word's closing ;;.
--
-- And the reader applies Asciidoctor's replacements to text, of which the
-- writer escapes only ->: an apostrophe or single quote turns curly, --
-- an em dash, ... an ellipsis, (C) (R) (TM) symbols, => <= <- arrows. A
-- choice labeled (C) becomes a copyright sign. Each is escaped as
-- Asciidoctor escapes it too: a backslash where there is a replacement to
-- escape (\' between letters, \--), {apos} for any other quote, which
-- Asciidoctor leaves alone and Pandoc's reader curls, and a one-character
-- passthrough for the arrows, whose backslash the reader keeps.
local ESCAPES = {
  { '::', ':{empty}:', 1 },          -- keep the second colon for the next
  { '--', '\\--' }, { '...', '\\...' },
  { '(C)', '\\(C)' }, { '(R)', '\\(R)' }, { '(TM)', '\\(TM)' },
  { '=>', '=++>++' }, { '<=', '<++=++' }, { '<-', '<++-++' },
}
local function wordy(ch)
  return ch ~= '' and (ch:match('[%w_]') ~= nil or ch:byte() >= 128)
end
local function escape_text(text)
  if not text:find("[:%-%.%(=<'/]") then return nil end
  local out, plain, i, changed = pandoc.Inlines({}), {}, 1, false
  local function flush()
    if #plain > 0 then out:insert(pandoc.Str(table.concat(plain))) end
    plain = {}
  end
  while i <= #text do
    local ch, done = text:sub(i, i), false
    -- A URL in text, which AsciiDoc makes a link; the author didn't.
    local rest = text:sub(i)
    if (rest:match('^https?://') or rest:match('^ftp://') or rest:match('^irc://')
        or rest:match('^mailto:')) and not wordy(text:sub(i - 1, i - 1)) then
      flush()
      out:insert(pandoc.RawInline('asciidoc', '\\'))
      changed = true
    end
    if ch == "'" then
      flush()
      local between = wordy(text:sub(i - 1, i - 1)) and wordy(text:sub(i + 1, i + 1))
      out:insert(pandoc.RawInline('asciidoc', between and "\\'" or '{apos}'))
      i, done, changed = i + 1, true, true
    else
      for _, e in ipairs(ESCAPES) do
        if text:sub(i, i + #e[1] - 1) == e[1] then
          flush()
          if e[3] then          -- '::': the first colon, then {empty}
            out:insert(pandoc.Str(':'))
            out:insert(pandoc.RawInline('asciidoc', '{empty}'))
            i = i + 1
          else
            out:insert(pandoc.RawInline('asciidoc', e[2]))
            i = i + #e[1]
          end
          done, changed = true, true
          break
        end
      end
    end
    if not done then
      plain[#plain + 1] = ch
      i = i + 1
    end
  end
  flush()
  return changed and out or nil
end

function Inlines(inlines)
  if not ADOC then return nil end
  local changed = false
  local out = pandoc.Inlines({})
  local line_start = true
  for i, el in ipairs(inlines) do
    if el.t == 'Note' and i > 1 and inlines[i - 1].t == 'Str' then
      out:insert(pandoc.RawInline('asciidoc', '{empty}'))
      changed = true
    end
    if line_start and el.t == 'Str' and el.text:match('^//') then
      -- {empty} expands before the reader looks for a comment, so the
      -- slashes go through as a passthrough instead.
      out:insert(pandoc.RawInline('asciidoc', '++//++'))
      el = pandoc.Str(el.text:sub(3))
      changed = true
    end
    -- A span, written [.role]#...#, or an anchor starting a line reads as
    -- a block attribute line for whatever block follows.
    if line_start and ((el.t == 'Str' and el.text ~= '' and hazard_at_start(el.text))
        or el.t == 'Span'
        or (el.t == 'RawInline' and el.format == 'asciidoc'
            and el.text:match('^%['))) then
      out:insert(pandoc.RawInline('asciidoc', '{empty}'))
      changed = true
    end
    local after = inlines[i + 1]
    local split = el.t == 'Str' and escape_text(el.text)
    if split then
      out:extend(split)
      changed = true
    elseif el.t == 'Code' and not el.text:find('::', 1, true)
        and not el.text:find('[`+]') and el.text:match('%S') then
      -- Literal code: no replacements, no escapes to write.
      out:insert(pandoc.RawInline('asciidoc', '`+' .. el.text .. '+`'))
      changed = true
    elseif el.t == 'Code' and el.text:find('::', 1, true) then
      -- Inline code can't hold raw markup, so it's written here, with the
      -- writer's own escaping, and its colons separated in that text.
      local written = pandoc.write(pandoc.Pandoc({ pandoc.Plain({ el }) }),
                                   'asciidoc', { wrap_text = 'none' })
      written = written:gsub('%s+$', '')
      repeat
        local n
        written, n = written:gsub('::', ':{empty}:')
      until n == 0
      out:insert(pandoc.RawInline('asciidoc', written))
      changed = true
    elseif el.t == 'Str' and el.text:match(';;$')
        and (after == nil or after.t == 'Space' or after.t == 'SoftBreak'
             or after.t == 'LineBreak') then
      out:insert(pandoc.Str(el.text:sub(1, -2)))
      out:insert(pandoc.RawInline('asciidoc', '{empty}'))
      out:insert(pandoc.Str(el.text:sub(-1)))
      changed = true
    else
      out:insert(el)
    end
    line_start = el.t == 'LineBreak' or el.t == 'SoftBreak'
  end
  -- A non-breaking space at the end of a text element is stripped by the
  -- reader as trailing space; {nbsp} isn't. One inside a word is kept.
  local final = pandoc.Inlines({})
  local NBSP = '\194\160'
  for _, el in ipairs(out) do
    local text, count = el.t == 'Str' and el.text, 0
    while text and text:sub(-2) == NBSP do    -- a Lua pattern can't repeat a group
      text, count = text:sub(1, -3), count + 1
    end
    if count > 0 then
      if text ~= '' then final:insert(pandoc.Str(text)) end
      for _ = 1, count do final:insert(pandoc.RawInline('asciidoc', '{nbsp}')) end
      changed = true
    else
      final:insert(el)
    end
  end
  return changed and final or nil
end

-- A quotation, written here with a delimiter longer than any inside it.
-- The writer nests a quotation in a quotation by wrapping the inner one in
-- an open block, which the reader loses (a blank line before its closing
-- "--"); AsciiDoc's own way is a longer delimiter, which it reads.
function BlockQuote(quote)
  if not ADOC then return nil end
  local text = pandoc.write(pandoc.Pandoc(quote.content), 'asciidoc',
                            { wrap_text = 'none' }):gsub('%s+$', '')
  local longest = 2
  for line in (text .. '\n'):gmatch('([^\n]*)\n') do
    if line:match('^_+$') then longest = math.max(longest, #line) end
  end
  local delimiter = string.rep('_', math.max(4, longest + 2))
  return pandoc.RawBlock('asciidoc', delimiter .. '\n' .. text .. '\n'
                                     .. delimiter .. '\n\n')
end

-- A footnote. AsciiDoc's footnote:[...] holds one paragraph on one line:
-- Pandoc's writer replaces a note of several paragraphs with the words
-- "[multiblock footnote omitted]", and the reader doesn't take a macro
-- spread over lines, so the paragraphs are joined with spaces, every word
-- kept. And the reader ends the macro at the first ], including the
-- writer's ++]++ for a bracket in the text; {startsb} and {endsb} are the
-- brackets, in Asciidoctor as in Pandoc's reader.
local function bracketed(str)
  if not str.text:find('[%[%]]') then return nil end
  local out = pandoc.Inlines({})
  for plain, bracket in str.text:gmatch('([^%[%]]*)([%[%]]?)') do
    if plain ~= '' then out:insert(pandoc.Str(plain)) end
    if bracket == '[' then out:insert(pandoc.RawInline('asciidoc', '{startsb}')) end
    if bracket == ']' then out:insert(pandoc.RawInline('asciidoc', '{endsb}')) end
  end
  return out
end

-- A note's blocks as one run of inlines: a list's items, a quotation's
-- paragraphs, each with its own formulas and links, a space between.
local function inlines_of(blocks)
  local words = pandoc.Inlines({})
  local function add(inlines)
    if #inlines == 0 then return end
    if #words > 0 then words:insert(pandoc.Space()) end
    words:extend(inlines)
  end
  for _, block in ipairs(blocks) do
    if block.t == 'Para' or block.t == 'Plain' or block.t == 'Header' then
      add(block.content)
    elseif block.t == 'BulletList' or block.t == 'OrderedList' then
      for _, item in ipairs(block.content) do add(inlines_of(item)) end
    elseif block.t == 'BlockQuote' or block.t == 'Div' then
      add(inlines_of(block.content))
    elseif block.t == 'CodeBlock' then
      add(pandoc.Inlines({ pandoc.Code(block.text) }))
    else
      add(pandoc.Inlines({ pandoc.Str(pandoc.utils.stringify(block)) }))
    end
  end
  return words
end

function Note(note)
  if not ADOC then return nil end
  local words = inlines_of(note.content)
  if #note.content > 1 then
    lost('footnote-paragraphs', pandoc.utils.stringify(words):sub(1, 60))
    io.stderr:write(('markdown-source: a footnote of %d paragraphs is written '
      .. 'as one: %s\n'):format(#note.content,
        pandoc.utils.stringify(words):sub(1, 60)))
  end
  words = words:walk({
    Str = bracketed,
    LineBreak = function() return pandoc.Space() end,
    SoftBreak = function() return pandoc.Space() end,
  })
  return pandoc.Note({ pandoc.Para(words) })
end

-- Italics holding a formula: the reader drops latexmath:[...] inside
-- constrained _..._, which the writer uses, and keeps it inside the
-- unconstrained __...__.
function Emph(emph)
  if not ADOC then return nil end
  local math = false
  emph.content:walk({ Math = function() math = true end })
  if not math then return nil end
  local out = pandoc.Inlines({ pandoc.RawInline('asciidoc', '__') })
  out:extend(emph.content)
  out:insert(pandoc.RawInline('asciidoc', '__'))
  return out
end

-- Display math inside a definition: the writer indents a definition's
-- lines, the math block's ++++ delimiters with them, which then aren't
-- delimiters, and the definition list breaks apart. Written as inline
-- math there: the formula stays, its display layout goes.
function DefinitionList(list)
  if not ADOC then return nil end
  local count = 0
  list = list:walk({ Math = function(m)
    if m.mathtype == 'DisplayMath' then
      count = count + 1
      return pandoc.Math('InlineMath', inline_tex(m.text))
    end
  end })
  if count == 0 then return nil end
  lost('math-in-definition-list', tostring(count) .. ' formula(s)')
  io.stderr:write(('markdown-source: %d display formula(s) in a definition '
    .. 'list written inline\n'):format(count))
  return list
end

-- An address with :: in it: the reader makes a description list of its
-- line whatever form the link takes, and expands no {empty} in an
-- address. The colons are written percent-encoded, which a server reads
-- as the same address; the one change this target makes to content.
function Link(link)
  -- Inside a link's text a ] ends the text, so a span, written
  -- [.role]#...#, cuts the link short: its text stays, the span goes. An
  -- anchor there, [[id]], moves to just before the link.
  local anchors, unwrapped = pandoc.Inlines({}), false
  if ADOC then
    link.content = link.content:walk({
      Span = function(span) unwrapped = true; return span.content end,
      RawInline = function(raw)
        if raw.format == 'asciidoc'
            and (raw.text:match('^%[%[') or raw.text:match('^{empty}%[%[')) then
          anchors:insert(pandoc.RawInline('asciidoc', (raw.text:gsub('^{empty}', ''))))
          return {}
        end
      end,
    })
  end
  if #anchors > 0 then
    local rest = Link(link)
    anchors:insert(rest or link)
    return anchors
  end
  -- A linked image: the image macro's link attribute, which the reader
  -- reads; it drops an image written inside a link's text.
  if ADOC and #link.content == 1 and link.content[1].t == 'RawInline'
      and link.content[1].text:match('^image:') then
    local text = link.content[1].text
    local target = link.target:gsub('"', '%%22')
    local join = text:match('%[%]$') and '' or ','
    return pandoc.RawInline('asciidoc',
      text:sub(1, -2) .. join .. 'link="' .. target .. '"]')
  end
  -- A link that is its own address, written as the bare URL, as the
  -- writer would: its text isn't escaped as a URL in text is. (One with a
  -- title is written below, with the title.)
  if ADOC and link.title == '' and pandoc.utils.stringify(link.content) == link.target
      and link.target:match('^%a[%w+.-]*:') and not link.target:find('::', 1, true)
      and not link.target:find('[%s%[%]]') then
    return pandoc.RawInline('asciidoc', link.target)
  end
  if ADOC and link.target:find('::', 1, true) then
    lost('address-colons', link.target)
    io.stderr:write(('markdown-source: %s written with %%3A for its "::"\n')
      :format(link.target))
    link.target = link.target:gsub('::', '%%3A%%3A')
    unwrapped = true
  end
  -- A link's title. The AsciiDoc writer drops every one; the macro's
  -- title attribute reads back, as an attribute asciidoc-source.lua moves
  -- to the title. The text is quoted, since a comma would split it, and
  -- the escaping pass still sees it, as ordinary inlines between the two
  -- raw pieces. A double quote in either has no form the reader keeps.
  if ADOC and link.title ~= '' then
    local title = link.title
    if title:find('"', 1, true) then
      local open = true
      title = title:gsub('"', function()
        open = not open
        return open and '\226\128\157' or '\226\128\156'
      end)
      lost('title-quotes', title)
      io.stderr:write(('markdown-source: a link title with double quotes is '
        .. 'written with typographic ones: %s\n'):format(title))
    end
    local content = link.content:walk({ Str = function(s)
      if s.text:find('"', 1, true) then
        return pandoc.Str((s.text:gsub('"', '\226\128\157')))
      end
    end })
    local out = pandoc.Inlines({ pandoc.RawInline('asciidoc',
      'link:' .. link.target .. '["') })
    out:extend(content)
    out:insert(pandoc.RawInline('asciidoc', '",title="' .. title .. '"]'))
    return out
  end
  -- The Markdown writer writes a link that is its own address as an
  -- autolink, <https://...>, which has no room for a title: a titled one
  -- is written in full.
  if not ADOC and link.title ~= ''
      and pandoc.utils.stringify(link.content) == link.target then
    local text = pandoc.write(pandoc.Pandoc({ pandoc.Plain(link.content) }),
                              'markdown', { wrap_text = 'none' }):gsub('%s+$', '')
    local title = link.title:gsub('\\', '\\\\'):gsub('"', '\\"')
    return pandoc.RawInline('markdown',
      '[' .. text .. '](' .. link.target .. ' "' .. title .. '")')
  end
  -- Returned when changed: nil would keep the link as it was read.
  if unwrapped then return link end
  return nil
end

-- Raw HTML, which the AsciiDoc writer drops, in a passthrough block.
function RawBlock(raw)
  if ADOC and raw.format == 'html' then return passthrough(raw.text) end
  return nil
end

-- An image, written here rather than by Pandoc's AsciiDoc writer, which
-- writes the alt as the macro's first value: unquoted, so its commas
-- split it and an = makes it an attribute, and the file name when there
-- is none. A named alt="..." comes back whole, commas, = and ] included,
-- in both Pandoc's reader and Asciidoctor; only a double quote inside
-- can't be written, and is written as a typographic one. A decorative
-- image says so with a role. Element functions run before the inline
-- pass, so the alt here is the author's text, unescaped.
function adoc_image(img)
  if img.classes:includes('decorative') then
    return pandoc.RawInline('asciidoc', 'image:' .. img.src .. '[role=decorative]')
  end
  local parts = {}
  local alt = pandoc.utils.stringify(img.caption)
  if alt ~= '' then
    if alt:find('"', 1, true) then
      local open = true
      alt = alt:gsub('"', function()
        open = not open
        return open and '\226\128\157' or '\226\128\156'
      end)
      lost('alt-quotes', alt)
      io.stderr:write(('markdown-source: an alt with double quotes is written '
        .. 'with typographic ones: %s\n'):format(alt))
    end
    parts[#parts + 1] = 'alt="' .. alt .. '"'
  end
  for _, name in ipairs({ 'width', 'height' }) do
    local value = img.attributes[name]
    if value and value ~= '' then
      value = value:gsub('px$', '')
      parts[#parts + 1] = value:match('^%d+$') and (name .. '=' .. value)
        or (name .. '="' .. value .. '"')
    end
  end
  return pandoc.RawInline('asciidoc',
    'image:' .. img.src .. '[' .. table.concat(parts, ',') .. ']')
end

-- A figure, written as its id, its caption as the block title, and its
-- image as a block macro.
function Figure(fig)
  if not ADOC then return nil end
  local body = fig.content
  if #body ~= 1 or (body[1].t ~= 'Plain' and body[1].t ~= 'Para')
      or #body[1].content ~= 1 or body[1].content[1].t ~= 'RawInline'
      or not body[1].content[1].text:match('^image:') then
    return nil
  end
  local lines = {}
  if fig.identifier ~= '' then lines[#lines + 1] = '[#' .. fig.identifier .. ']' end
  -- The caption is the block title, which is one line: its line breaks
  -- and paragraphs become spaces. A second line would start a paragraph,
  -- and take the image macro into it as inline text.
  local words = pandoc.Inlines({})
  for _, block in ipairs(fig.caption.long) do
    if block.content then
      if #words > 0 then words:insert(pandoc.Space()) end
      words:extend(block.content)
    end
  end
  words = words:walk({ LineBreak = function() return pandoc.Space() end,
                       SoftBreak = function() return pandoc.Space() end })
  if #words > 0 then
    local text = pandoc.write(pandoc.Pandoc({ pandoc.Plain(words) }), 'asciidoc',
                              { wrap_text = 'none' }):gsub('%s+$', ''):gsub('\n', ' ')
    if text ~= '' then lines[#lines + 1] = '.' .. text end
  end
  lines[#lines + 1] = 'image::' .. body[1].content[1].text:sub(7)
  return pandoc.RawBlock('asciidoc', table.concat(lines, '\n') .. '\n\n')
end

local function not_a_figure(block)
  if ADOC then return nil end   -- an inline image stays inline in AsciiDoc
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

-- Inline math is latexmath:[...], which the reader ends at the first ],
-- escaped or not: [0,1] cuts the formula short. TeX's own names for the
-- brackets render the same. A root's index, \sqrt[3], can't take them;
-- there the bracket is escaped as Asciidoctor reads it, and reported.
function inline_tex(text)
  -- Word's thin space at the end, "\\ ", goes as it does for Markdown;
  -- a backslash left last would escape the macro's closing bracket.
  text = text:gsub('%s*\\%s+$', ''):gsub('^%s+', ''):gsub('%s+$', '')
  if text:match('\\$') then text = text .. ' ' end
  if not text:find('[%[%]]') then return text end
  if text:find('\\sqrt%s*%[') then
    lost('root-index', text)
    io.stderr:write(('markdown-source: a root index in brackets is written '
      .. 'for Asciidoctor, not Pandoc\'s reader: %s\n'):format(text))
    return (text:gsub('%]', '\\]'))
  end
  return (text:gsub('%[', '\\lbrack '):gsub('%]', '\\rbrack '))
end

function Math(m)
  if ADOC and m.mathtype == 'InlineMath' then
    local text = inline_tex(m.text)
    if text ~= m.text then return pandoc.Math('InlineMath', text) end
    return nil
  end
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

-- AsciiDoc numbers sections in sequence under the document title: "="
-- is the title, "==" the first level. A page's title is its document
-- title and its sections start at level 2, which the writer writes as
-- "===", skipping a level, and the reader then takes "===" for level 1
-- and "====" for level 3. So under a title they move up one; reading
-- AsciiDoc moves them back (asciidoc-source.lua).
-- A page's subtitle and the blocks before and after it, which the
-- pipeline renders on a book's opening page and the AsciiDoc writer's
-- header leaves out: the subtitle as an attribute entry, the blocks in
-- open blocks named for them, which reading lifts back into metadata.
-- They come from metadata, where this filter's handlers never ran, so
-- they run here first.
local function written_meta(doc)
  local handlers = { Inlines = Inlines, Math = Math, Emph = Emph, Image = Image,
                     Link = Link, Span = Span, Note = Note }
  local function prepared(blocks)
    return pandoc.Pandoc(blocks):walk(handlers):walk({ Figure = Figure,
      Table = Table, RawBlock = RawBlock, BlockQuote = BlockQuote }).blocks
  end
  local front, back = pandoc.Blocks({}), pandoc.Blocks({})
  if doc.meta.subtitle then
    front:insert(pandoc.RawBlock('asciidoc', ':subtitle: '
      .. pandoc.utils.stringify(doc.meta.subtitle):gsub('\n', ' ') .. '\n'))
  end
  for _, key in ipairs({ 'include-before', 'include-after' }) do
    local value = doc.meta[key]
    if value then
      -- A metadata value has no .t in Pandoc 3; its type says what it is.
      -- The template would write the field itself, unwrapped, so it goes.
      doc.meta[key] = nil
      local blocks = pandoc.Blocks({})
      local kind = pandoc.utils.type(value)
      for _, item in ipairs(kind == 'List' and value or { value }) do
        local t = pandoc.utils.type(item)
        if t == 'Blocks' then blocks:extend(item)
        elseif t == 'Inlines' then blocks:insert(pandoc.Para(item))
        elseif t == 'string' then blocks:insert(pandoc.Para({ pandoc.Str(item) })) end
      end
      if #blocks > 0 then
        local into = key == 'include-before' and front or back
        into:insert(open_block(key, prepared(blocks)))
      end
    end
  end
  if #front == 0 and #back == 0 then return false end
  doc.blocks = front .. doc.blocks .. back
  return true
end

function Pandoc(doc)
  if not ADOC then return nil end
  local changed = written_meta(doc)
  if doc.meta.title == nil then return changed and doc or nil end
  local lowest = math.huge
  doc:walk({ Header = function(h) lowest = math.min(lowest, h.level) end })
  if lowest == math.huge then return changed and doc or nil end
  -- The lowest heading is written "==", the first level under a title. A
  -- page whose headings start somewhere else (at the title's own level, or
  -- a level below where they'd be expected, as DCIC's do) says by how
  -- much, and reading puts them back: AsciiDoc has no way to skip a level
  -- under the title, and Pandoc's reader renumbers a first heading that
  -- does.
  local offset = lowest - 2
  if offset ~= 0 then
    doc.blocks:insert(1, pandoc.RawBlock('asciidoc', ':heading-offset: '
      .. tostring(offset) .. '\n'))
  end
  return doc:walk({ Header = function(h)
    h.level = h.level - (lowest - 1)
    return h
  end })
end

-- An example list: Pandoc's Markdown writer writes one as a numbered
-- list, (1), (2), which reads back as a numbered list, not examples, so
-- their numbering no longer runs on and a reference to one by label is
-- already a number. Reported, not changed.
function OrderedList(list)
  if not ADOC and list.listAttributes.style == 'Example' then
    lost('example-list', pandoc.utils.stringify(list.content[1] or {}):sub(1, 60))
  end
end

-- For AsciiDoc, two passes: the tables that go as HTML, from the text as
-- it stands, then everything else. A file that returns filters runs no
-- global function, so every handler is named.
if ADOC then
  return {
    { Table = adoc_html_table, Span = merge_spans },
    { Div = Div, Table = Table, Image = Image, Para = Para, Plain = Plain,
      Math = Math, Header = Header, Meta = Meta, Span = Span,
      Inlines = Inlines, RawBlock = RawBlock, Figure = Figure, Link = Link,
      Note = Note, Emph = Emph, DefinitionList = DefinitionList,
      BlockQuote = BlockQuote, Pandoc = Pandoc },
  }
end
