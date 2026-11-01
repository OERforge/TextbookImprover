--[[
markdown-reader.lua

Reads a Markdown source as Pandoc's markdown does, but takes a raw HTML
code element -- <code>, <kbd>, <samp>, <var>, or <tt> -- as written, as
an HTML source's is read, where Pandoc's reader reads what's between its
tags as Markdown (PANDOC-NOTES, the Markdown reader): smart punctuation
curled a quotation mark (<code>open("c:\\projects")</code> was open(“c:
\projects”)), made -- a dash and ... an ellipsis, and a backslash was
taken for an escape, so two were one; and in a paragraph the element's
tags, raw HTML, were left out of a PDF, its text set as the text around
it. Here the element is the HTML reader's reading of it, a Code element
(a Span of class kbd for <kbd>), as markdown-html.lua reads the rest of
a Markdown book's HTML, so that it comes out as an HTML book's does.

How: before Pandoc reads the source, each such element on one line, its
tags matched, is written as a tag of a name no tag in the source has,
<tv0-N>, its number N, and spaces before its '>' to make it as wide as
the element, which the Markdown reader keeps as raw HTML; each is put
back as the HTML reader reads the element. Where the element was text to
Pandoc, in a code span or block, a <pre>, or a comment, the tag is put
back as the element was written. As wide as the element, the tag moves
nothing in a table whose columns are where its lines put them: an empty
span, the first marker, was wider than most elements, and in a simple
table it moved a row's words past its column's edge into the next
column. And a span holding the element's text was no span to the
Markdown reader where the text had Markdown's marks, as f(*args, **kw)
has. A heading takes the id the source as written gives it, since the
reader makes an id from a heading's text. The page is read as Pandoc
reads it instead, as before, where the marking would change how its
blocks are read (their kinds, a heading's level, a list's items, a
table's rows and cells, and the text of a table's cells outside the
elements) or where a marked element can't be put back. A character's
width is counted as Pandoc counts it for the main ranges of Unicode's
East Asian widths; where the count is wrong, a word that moves to
another column is found by the cells' text, and the page is read as
Pandoc reads it. In a YAML metadata block, whose strings have escapes of
their own, nothing is marked.

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

local ELEMENTS = { code = true, kbd = true, samp = true, var = true, tt = true }

-- How many columns a character takes in a table whose columns its lines
-- place, as Pandoc counts them (doclayout's realLength): two for an East
-- Asian wide or full-width one, none for a combining mark or a zero-width
-- space or joiner, one for any other. The ranges are Unicode's East Asian
-- Width property's main ones, not all of them.
local WIDE = { { 0x1100, 0x115F }, { 0x2E80, 0x303E }, { 0x3041, 0x33FF }, { 0x3400, 0x4DBF },
               { 0x4E00, 0x9FFF }, { 0xA000, 0xA4CF }, { 0xAC00, 0xD7A3 }, { 0xF900, 0xFAFF },
               { 0xFE30, 0xFE4F }, { 0xFF00, 0xFF60 }, { 0xFFE0, 0xFFE6 }, { 0x1F300, 0x1F64F },
               { 0x1F900, 0x1F9FF }, { 0x20000, 0x2FFFD }, { 0x30000, 0x3FFFD } }
local ZERO = { { 0x0300, 0x036F }, { 0x1AB0, 0x1AFF }, { 0x1DC0, 0x1DFF }, { 0x200B, 0x200F },
               { 0x20D0, 0x20FF }, { 0xFE20, 0xFE2F } }

local function within(ranges, code)
  for _, range in ipairs(ranges) do
    if code >= range[1] and code <= range[2] then return true end
  end
  return false
end

-- text's width in a table's columns, or nil where it isn't UTF-8. Pandoc
-- gives a reader its text with tabs made spaces.
local function width(text)
  if not utf8.len(text) then return nil end
  local total = 0
  for _, code in utf8.codes(text) do
    total = total + (within(WIDE, code) and 2 or within(ZERO, code) and 0 or 1)
  end
  return total
end

-- A tag name no tag in texts begins with: tv0, tv1, and so on.
local function free_prefix(texts)
  local all = table.concat(texts, '\n'):lower()
  local n = 0
  while all:find('<tv' .. n .. '-', 1, true) do n = n + 1 end
  return 'tv' .. n
end

-- The position of the '>' that ends a tag whose name ends before pos, or
-- nil where the line ends first; a '>' in a quoted value doesn't end it.
local function tag_end(text, pos)
  local quote = nil
  for p = pos, #text do
    local c = text:sub(p, p)
    if c == '\n' then return nil end
    if quote then
      if c == quote then quote = nil end
    elseif c == '"' or c == "'" then
      quote = c
    elseif c == '>' then
      return p
    elseif c == '<' then
      return nil
    end
  end
  return nil
end

-- (start, end) of the tag that closes an element named name whose
-- contents start at pos, the same element inside counted, on its line;
-- nil where the line ends first.
local function matching_close(text, pos, name)
  local line_end = text:find('\n', pos, true) or (#text + 1)
  local rest = text:sub(pos, line_end - 1):lower()
  local depth, p = 1, 1
  while true do
    local s = rest:find('<', p, true)
    if not s then return nil end
    local _, b = rest:find('^</%s*' .. name .. '%s*>', s)
    if b then
      depth = depth - 1
      if depth == 0 then return pos + s - 1, pos + b - 1 end
      p = b + 1
    else
      local _, d = rest:find('^<' .. name .. '[%s>]', s)
      if d then depth = depth + 1 end
      p = (d or s) + 1
    end
  end
end

-- Lines of a YAML metadata block, as Pandoc finds one, or more: a line of
-- three hyphens not followed by a blank line, to a line of three hyphens or
-- three dots. Pandoc tries one at each block's start (yamlMetaBlock'), so
-- after a blank line, and after a block that ends without one: a fenced
-- code block, a div, raw HTML, and a table were measured; after a line of
-- text, a heading, or a list's item, the hyphens underline it or go with
-- it. A line that could end such a block counts. {line number: true}.
local function yaml_lines(text)
  local lines = {}
  for line in (text .. '\n'):gmatch('(.-)\r?\n') do lines[#lines + 1] = line end
  local inside, n = {}, 1
  while n <= #lines do
    if lines[n]:match('^%-%-%-%s*$')
        and (n == 1 or lines[n - 1]:match('^%s*$') or lines[n - 1]:match('^%s*[`~:<|+]'))
        and lines[n + 1] and not lines[n + 1]:match('^%s*$') then
      local last = nil
      for m = n + 1, #lines do
        if lines[m]:match('^%-%-%-%s*$') or lines[m]:match('^%.%.%.%s*$') then
          last = m
          break
        end
      end
      if last then
        for m = n, last do inside[m] = true end
        n = last
      end
    end
    n = n + 1
  end
  return inside
end

-- text with each raw code element on one line written as a tag of prefix's
-- name and its number, as wide as the element, the same tag for elements
-- written alike, so that a heading's and a link's text that name one
-- another still do; originals[k] the element as written, markers[k] the
-- tag that stands for it, numbers[the element] k. Not an element holding a
-- backtick, which may be a code span's, so that two spans became one
-- (`<code>` and `</code>`), nor one holding \|, which in a pipe table is
-- the table's escape, not the code's.
local function mark(text, originals, markers, numbers, prefix)
  local yaml = yaml_lines(text)
  local out, i, line, counted = {}, 1, 1, 1
  while i <= #text do
    local s = text:find('<', i, true)
    if not s then break end
    -- The line s is on, counted from where the count had got to.
    for _ in text:sub(counted, s - 1):gmatch('\n') do line = line + 1 end
    counted = s
    local done = false
    local slashes = 0
    while s - slashes - 1 >= 1 and text:sub(s - slashes - 1, s - slashes - 1) == '\\' do
      slashes = slashes + 1
    end
    local name = text:match('^<(%a+)', s)
    if name and ELEMENTS[name:lower()] and slashes % 2 == 0 and not yaml[line] then
      local after = s + 1 + #name
      local c = text:sub(after, after)
      if c == '>' or c:match('%s') then
        local open_end = tag_end(text, after)
        if open_end and text:sub(open_end - 1, open_end - 1) ~= '/' then
          local close_start, close_end = matching_close(text, open_end + 1, name:lower())
          local element = close_start and text:sub(s, close_end)
          local k = element and (numbers[element] or #originals + 1)
          local tag = k and '<' .. prefix .. '-' .. k
          local wide = element and width(element)
          if wide and wide > #tag and not element:find('`', 1, true)
              and not element:find('\\|', 1, true) then
            if not numbers[element] then
              numbers[element] = k
              originals[k] = element
              markers[k] = tag .. string.rep(' ', wide - #tag - 1) .. '>'
            end
            out[#out + 1] = text:sub(i, s - 1)
            out[#out + 1] = markers[k]
            i = close_end + 1
            done = true
          end
        end
      end
    end
    if not done then
      out[#out + 1] = text:sub(i, s)
      i = s + 1
    end
  end
  out[#out + 1] = text:sub(i)
  return table.concat(out)
end

-- The element as the HTML reader reads it, as inlines.
local function read_element(html)
  local out = pandoc.Inlines({})
  for _, block in ipairs(pandoc.read(html, 'html+raw_html+epub_html_exts').blocks) do
    if block.t == 'Plain' or block.t == 'Para' then out:extend(block.content) end
  end
  return out
end

-- The raw code element tag el is: (name, closing?), or nil.
local function code_tag(el)
  if el.t ~= 'RawInline' or el.format ~= 'html' then return nil end
  local slash, name = el.text:match('^<(/?)(%a+)')
  if name and ELEMENTS[name:lower()] and not el.text:match('/%s*>$') then
    return name, slash == '/'
  end
  return nil
end

-- A table's cell's text without its raw code elements, as Pandoc's reading
-- has them (a tag, what Markdown made of the text, and a tag), and without
-- the tags that stand for them (marker).
local function bare_text(blocks, marker)
  local function drop(inlines)
    local out, depth = pandoc.Inlines({}), 0
    for _, el in ipairs(inlines) do
      local name, closing = code_tag(el)
      if marker and marker(el) then
        -- an element, marked
      elseif name then
        depth = math.max(0, depth + (closing and -1 or 1))
      elseif depth == 0 then
        out:insert(el)
      end
    end
    return out
  end
  return pandoc.utils.stringify(pandoc.Blocks(blocks):walk({ Inlines = drop }))
end

-- What the blocks are, in order, and a table's columns' alignments and
-- widths, its rows and cells and their text but the elements', a list's
-- items, and a heading's level: what the marking mustn't change. A table
-- whose columns are where its lines put them had its words moved from one
-- column to the next by a marker wider than its element, its rows and
-- cells as many, and a header's alignment changed with where its text
-- stood; a pipe table's widths come of its lines' lengths.
local function shape(doc, marker)
  local parts = {}
  local function add(text) parts[#parts + 1] = text end
  local function rows(list)
    for _, row in ipairs(list) do
      add('row ' .. #row.cells)
      for _, cell in ipairs(row.cells) do add('cell ' .. bare_text(cell.contents, marker)) end
    end
  end
  doc:walk({
    traverse = 'topdown',
    Block = function(block)
      add(block.t)
      if block.t == 'Header' then
        add(block.level)
      elseif block.t == 'BulletList' or block.t == 'OrderedList'
          or block.t == 'DefinitionList' then
        add('items ' .. #block.content)
      elseif block.t == 'Table' then
        for _, spec in ipairs(block.colspecs) do
          add('column ' .. tostring(spec[1]) .. ' ' .. tostring(spec[2]))
        end
        rows(block.head.rows)
        for _, body in ipairs(block.bodies) do
          rows(body.head)
          rows(body.body)
        end
        rows(block.foot.rows)
      end
    end,
  })
  return table.concat(parts, '\n')
end

-- text as JSON writes it inside a string's quotes.
local function json_text(text)
  return pandoc.json.encode(text):sub(2, -2)
end

local function name_of(input)
  local name = input[1] and input[1].name or ''
  return name:match('[^/\\]+$') or '-'
end

-- text with every old in it made new.
local function replace_all(text, old, new)
  local out, i = {}, 1
  while true do
    local at, stop = text:find(old, i, true)
    if not at then break end
    out[#out + 1] = text:sub(i, at - 1)
    out[#out + 1] = new
    i = stop + 1
  end
  out[#out + 1] = text:sub(i)
  return table.concat(out)
end

-- The targets of a document's links within it, in order.
local function link_targets(doc)
  local targets = {}
  doc:walk({ traverse = 'topdown', Link = function(link)
    targets[#targets + 1] = link.target
  end })
  return targets
end

function Reader(input, opts)
  local plain = pandoc.read(input, 'markdown', opts)
  local texts = {}
  for _, source in ipairs(input) do texts[#texts + 1] = source.text end
  local prefix = free_prefix(texts)
  local sources, originals, markers, numbers = {}, {}, {}, {}
  for _, source in ipairs(input) do
    sources[#sources + 1] = { name = source.name,
                              text = mark(source.text, originals, markers, numbers, prefix) }
  end
  if #originals == 0 then return plain end
  local doc = pandoc.read(sources, 'markdown', opts)
  -- Each tag the reader kept as raw HTML made a span of its number, with
  -- an attribute no span in the source has (free_prefix); a tag left is
  -- text to the reader, in code or a comment, as many times as Pandoc
  -- repeats it (an image's description is its figure's caption too), and
  -- is put back as written.
  local key = 'data-' .. prefix .. '-verbatim'
  local pattern = '^<' .. prefix .. '%-(%d+)%s*>$'
  local found = {}
  doc = doc:walk({ RawInline = function(raw)
    if raw.format ~= 'html' then return nil end
    local k = tonumber(raw.text:match(pattern))
    if not k or not originals[k] then return nil end
    found[k] = true
    return pandoc.Span({}, pandoc.Attr('', {}, { { key, tostring(k) } }))
  end })
  local function marker(el)
    return el.t == 'Span' and tonumber(el.attributes[key]) or nil
  end
  local json = pandoc.write(doc, 'json')
  local ok, back = true, false
  for k = 1, #originals do
    local text = json_text(markers[k])
    if json:find(text, 1, true) then
      json = replace_all(json, text, json_text(originals[k]))
      back = true
    elseif not found[k] then
      ok = false
    end
  end
  if ok and back then doc = pandoc.read(json, 'json') end
  if ok and shape(doc, marker) ~= shape(plain) then ok = false end
  -- A link to a heading by its text goes where Pandoc's reading has it go,
  -- since a heading's id, made from its text, is the plain reading's below.
  local plain_targets, targets = link_targets(plain), link_targets(doc)
  if ok and #plain_targets ~= #targets then ok = false end
  if not ok then
    io.stderr:write(('[markdown-reader] %s: its %d raw code element(s) are read as '
      .. 'Markdown, as Pandoc reads them: taken as written, they changed how the page\'s '
      .. 'blocks were read\n'):format(name_of(input), #originals))
    return plain
  end
  local taken, count, n = {}, 0, 0
  doc = doc:walk({ traverse = 'topdown', Link = function(link)
    n = n + 1
    if link.target ~= plain_targets[n] then
      link.target = plain_targets[n]
      return link
    end
  end })
  doc = doc:walk({ Span = function(span)
    local k = marker(span)
    if not k then return nil end
    if not taken[k] then taken[k], count = true, count + 1 end
    return read_element(originals[k])
  end })
  -- Each heading's id the one Pandoc gives it read as written: made from a
  -- heading's text, which the element's is missing from here.
  local ids, m = {}, 0
  plain:walk({ traverse = 'topdown', Header = function(h) ids[#ids + 1] = h.identifier end })
  doc = doc:walk({ traverse = 'topdown', Header = function(h)
    m = m + 1
    if h.identifier ~= ids[m] then
      h.identifier = ids[m]
      return h
    end
  end })
  if count > 0 then
    io.stderr:write(('[markdown-reader] %s: %d raw code element(s) taken as written\n')
      :format(name_of(input), count))
  end
  return doc
end
