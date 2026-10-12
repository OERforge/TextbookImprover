-- deck-pptx.lua -- a deck made ready for Pandoc's PowerPoint writer. Runs
-- when convert.py writes a deck's PowerPoint file, after target-blocks.lua;
-- lib/pptxtarget.py then finishes what the writer wrote, from what this
-- records in DECK_PPTX_RECORD. DECK_SLIDE_LEVEL is the slide level the
-- writer is given, DECK_NOTES the target's slides.notes.
--
-- What the writer does with a deck, read in Writers/Powerpoint/ at 3.12.1
-- (Presentation.hs: splitBlocks, bodyBlocksToSlide, blockToShape,
-- replaceAnchor, getMetaSlide; Output.hs: makePicElements) and measured,
-- and what's done about it here:
--
-- 1. Only a slide's own blocks, and a column's, are shapes: a picture, a
--    table, or text. A div other than a slide's columns, its notes, or an
--    incremental list is read as text, a table in it dropped and a slide
--    in it run into the one before, so each div is unwrapped, its
--    identifier kept for a link to it: the filter's table-wrapper, and a
--    passage in another language, whose language the writer doesn't
--    write (counted, with the spans that say one). A div is a slide's
--    notes only when notes is its one class (isNotesDiv), and one with
--    another class too was shown on the slide, so it's given that one.
-- 2. A pause, Pandoc's ". . .", is written as three dots: it goes, and its
--    slide shows all at once.
-- 3. A paragraph that opens with a picture ends its slide, the rest of its
--    words making a slide with no title, or, in a column, left out with
--    the column's other blocks after it; a figure doesn't. So each such
--    picture is made a figure of its own, the rest of its paragraph a
--    paragraph after it. A figure of more than one block, as a ::: figure
--    div makes one, is written as text, its images as their alt text, so
--    each picture in it is made a figure too, the figure's identifier the
--    first's and its caption the last's.
-- 4. The writer cuts a slide where a second table, or a table after a
--    picture, begins one with no title, and around a slide's columns; and
--    it places a picture where the slide's other content goes, over the
--    text after it, a table before it, or another picture. So a slide is
--    cut in those places and before what follows a picture, each part
--    after the first titled as the slide is with its number after it,
--    " (2)", as the PowerPoint remediation gives a second title. A
--    picture after text is the writer's own layout, the text beside it.
--    Notes between a slide's heading and its columns, which would leave
--    the heading a slide of its own, go after the columns. What a column
--    holds after where the writer would cut it is left out by the writer,
--    and counted, but on a comparison slide, whose columns it shows whole.
-- 5. A picture's description is its title and its file's path, and its
--    image's alt text is shown under it as a caption, a figure's own
--    caption dropped. Each picture is titled oer-pic-N, for pptxtarget.py
--    to find it and write its alt text, or its decorative mark, in its
--    description; and it shows a figure's caption, as the deck's page and
--    PDF do, and no other. A caption that repeats the alt text is
--    recorded, for pptxtarget.py to mark decorative, as the page hides
--    one from a screen reader (aria-hidden).
-- 6. An image in a line of text, a list, or a table is written as its alt
--    text: each is counted.
-- 7. A table's header column isn't written: each table's first cell
--    carries a marker naming it, which pptxtarget.py takes out again, and
--    whether its first column is its header is recorded.
-- 8. A link to a place on a slide works only to a heading, which the
--    writer makes a link to its slide: a link to anything else is pointed
--    at a heading on the slide the place is on, and one with none is
--    counted, since the writer takes the link out and leaves its words.
-- 9. An institute isn't shown: it goes under the authors, where beamer
--    puts it, and the authors alone are recorded, as the file's creator.
-- 10. title-meta, a title for the file's properties, is recorded, for
--    pptxtarget.py to write there.
-- 11. With slides.notes omitted, the speaker notes are left out.
-- 12. A display equation has a paragraph's space before it, as the text
--    around it has, and the paragraph after it too: each, but where the
--    deck gives some of its own, is marked for pptxtarget.py to give half
--    a line before it, as the page and the PDF set one off.
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

local stringify = pandoc.utils.stringify

local RECORD = os.getenv('DECK_PPTX_RECORD')
local LEVEL = tonumber(os.getenv('DECK_SLIDE_LEVEL') or '')
local OMIT_NOTES = os.getenv('DECK_NOTES') == 'omitted'
local PICTURE = 'oer-pic-'
-- A table's marker: private-use characters around its number, which no
-- deck's own text holds.
local TABLE_OPEN, TABLE_CLOSE = '\u{E000}oer-tbl-', '\u{E001}'

local KEPT_DIVS = { 'notes', 'columns', 'column', 'incremental', 'nonincremental' }

local record = {
  pictures = {}, tables = {}, inline_images = 0, pauses = 0, languages = 0,
  retargeted = 0, unlinked = 0, notes = 0, institute = false, cut = 0, added = 0,
  continued = 0, column_blocks = 0,
}
local pictures, tables = 0, 0

local function squeezed(text)
  return (text:gsub('%s+', ' '):gsub('^ ', ''):gsub(' $', ''))
end

local function kept(div)
  for _, class in ipairs(KEPT_DIVS) do
    if div.classes:includes(class) then return true end
  end
  return false
end

local function is_notes(block)
  return block.t == 'Div' and block.classes:includes('notes')
end

-- A pause as the slide writers know one (isPause, Writers/HTML.hs).
local function is_pause(block)
  if block.t ~= 'Para' then return false end
  local c = block.content
  return #c == 5 and c[1].t == 'Str' and c[1].text == '.' and c[2].t == 'Space'
    and c[3].t == 'Str' and c[3].text == '.' and c[4].t == 'Space'
    and c[5].t == 'Str' and c[5].text == '.'
end

-- As the filter marks an image decorative (figures-and-tables.lua), and
-- the Word target reads the mark (docxtarget._decorative).
local function decorative(img)
  return stringify(img.caption) == ''
    and (img.attributes['aria-hidden'] == 'true' or img.attributes.role == 'presentation')
end

-- An image's alt text as the HTML writer gives it: its alt attribute, else
-- its description.
local function alt_text(img)
  if img.attributes.alt ~= nil then return squeezed(img.attributes.alt) end
  return squeezed(stringify(img.caption))
end

-- The inline a picture is made of, if a paragraph opens with one: an
-- image, or a link whose first inline is an image; and that image.
local function opening_image(block)
  if (block.t ~= 'Para' and block.t ~= 'Plain') or #block.content == 0 then
    return nil
  end
  local first = block.content[1]
  if first.t == 'Image' then return first, first end
  if first.t == 'Link' and first.content[1] and first.content[1].t == 'Image' then
    return first, first.content[1]
  end
  return nil
end

-- What the writer makes a picture of, and what it makes a picture or a
-- table of (notText).
local function is_picture(block)
  return block.t == 'Figure' or opening_image(block) ~= nil
end

local function is_shape(block)
  return block.t == 'Table' or is_picture(block)
end

-- An image the writer makes a picture of: titled to be found, its alt text
-- and mark recorded, and shown with a caption only when it's a figure's
-- with one (caption: the figure's, as inlines, or nil).
local function picture(img, caption)
  pictures = pictures + 1
  local mark = decorative(img)
  local alt = mark and '' or alt_text(img)
  local own = caption and squeezed(stringify(caption)) or ''
  record.pictures[tostring(pictures)] = {
    alt = alt, decorative = mark, caption = own ~= '', repeats = own ~= '' and own == alt,
  }
  img.title = PICTURE .. pictures
  img.caption = own ~= '' and caption or pandoc.Inlines({})
end

-- Display equations, set off by space as the page and the PDF set them
-- off: each in a paragraph of its own, as the writer makes one
-- (fixDisplayMath, in Writers/Powerpoint.hs), and it, and the paragraph
-- after it, marked with SPACE_MARK for pptxtarget.py to give space
-- before, unless the deck gives it some there itself that the writer
-- keeps: an empty paragraph or a line break. Raw HTML or LaTeX, a \vspace
-- say, the writer leaves out, so it neither gives space nor stands between
-- an equation and the text around it. An equation's mark is the first
-- character of its TeX, which the writer would part from it as a
-- paragraph of its own; the paragraph's, its first inline.
local SPACE_MARK = '\u{E002}'

local function is_display(inline)
  return inline.t == 'Math' and inline.mathtype == 'DisplayMath'
end

-- A space, or what the writer leaves out of a line, raw HTML or LaTeX.
local function is_blank(inline)
  return inline.t == 'Space' or inline.t == 'SoftBreak' or inline.t == 'RawInline'
    or (inline.t == 'Str' and inline.text:gsub('\u{A0}', ''):match('^%s*$') ~= nil)
end

local function textual(block)
  return block ~= nil and (block.t == 'Para' or block.t == 'Plain')
end

-- The first or the last inline of a list but a blank one.
local function edge(inlines, last)
  local from, to, step = 1, #inlines, 1
  if last then from, to, step = #inlines, 1, -1 end
  for k = from, to, step do
    if not is_blank(inlines[k]) then return inlines[k] end
  end
  return nil
end

local function spaced_edge(block, last)
  local inline = textual(block) and edge(block.content, last)
  return inline ~= nil and inline ~= false and inline.t == 'LineBreak'
end

-- An empty paragraph, or one of line breaks.
local function is_space_block(block)
  if not textual(block) then return false end
  for _, inline in ipairs(block.content) do
    if not (is_blank(inline) or inline.t == 'LineBreak') then return false end
  end
  return true
end

local function display_alone(block)
  if not textual(block) then return false end
  local found = false
  for _, inline in ipairs(block.content) do
    if is_display(inline) then
      found = true
    elseif not (is_blank(inline) or inline.t == 'LineBreak') then
      return false
    end
  end
  return found
end

-- A paragraph as paragraphs, each display equation in it one of its own.
local function split_displays(block)
  local displays, other = 0, false
  for _, inline in ipairs(block.content) do
    if is_display(inline) then
      displays = displays + 1
    elseif not is_blank(inline) then
      other = true
    end
  end
  if displays == 0 or (displays == 1 and not other) then return { block } end
  local make = block.t == 'Para' and pandoc.Para or pandoc.Plain
  local out, current = {}, pandoc.Inlines({})
  local function flush()
    while #current > 0 and is_blank(current[1]) do current:remove(1) end
    while #current > 0 and is_blank(current[#current]) do current:remove(#current) end
    if #current > 0 then table.insert(out, make(current)) end
    current = pandoc.Inlines({})
  end
  for _, inline in ipairs(block.content) do
    if is_display(inline) then
      flush()
      table.insert(out, make({ inline }))
    else
      current:insert(inline)
    end
  end
  flush()
  return out
end

-- The block nearest k in list, before it (step -1) or after it (1), but
-- raw HTML or LaTeX, which the writer leaves out: (index, block) or nil.
local function neighbor(list, k, step)
  local j = k + step
  while list[j] ~= nil and list[j].t == 'RawBlock' do j = j + step end
  if list[j] == nil then return nil end
  return j, list[j]
end

local function space_displays(blocks)
  local list = pandoc.Blocks({})
  for _, block in ipairs(blocks) do
    if textual(block) then list:extend(split_displays(block)) else list:insert(block) end
  end
  local marks = {}
  for k, block in ipairs(list) do
    if display_alone(block) then
      local _, before = neighbor(list, k, -1)
      local at, after = neighbor(list, k, 1)
      if before ~= nil and not is_space_block(before) and not spaced_edge(before, true)
          and not spaced_edge(block, false) then
        marks[k] = true
      end
      if textual(after) and not display_alone(after) and not is_space_block(after)
          and not opening_image(after) and not spaced_edge(block, true)
          and not spaced_edge(after, false) then
        marks[at] = true
      end
    end
  end
  for k in pairs(marks) do
    local marked = false
    if display_alone(list[k]) then
      for _, inline in ipairs(list[k].content) do
        if is_display(inline) and not marked then
          inline.text = SPACE_MARK .. inline.text
          marked = true
        end
      end
    end
    if not marked then list[k].content:insert(1, pandoc.Str(SPACE_MARK)) end
  end
  return list
end

-- A paragraph's inlines after its first, the spaces and breaks it opens
-- with left out.
local function rest_of(inlines)
  local rest = pandoc.Inlines({})
  for i = 2, #inlines do rest:insert(inlines[i]) end
  while #rest > 0 and (rest[1].t == 'Space' or rest[1].t == 'SoftBreak'
                       or rest[1].t == 'LineBreak') do
    rest:remove(1)
  end
  return rest
end

-- A slide's or a column's blocks, each picture a figure of its own: a
-- paragraph that opens with one is a figure, and the rest of its words a
-- paragraph after it, itself made figures while it opens with a picture.
local function shapes(blocks)
  local out = pandoc.Blocks({})
  for _, block in ipairs(blocks) do
    if block.t == 'Figure' and #block.content == 1 and opening_image(block.content[1]) then
      local first, img = opening_image(block.content[1])
      picture(img, pandoc.utils.blocks_to_inlines(block.caption.long))
      local rest = rest_of(block.content[1].content)
      block.content = pandoc.Blocks({ pandoc.Plain({ first }) })
      out:insert(block)
      if #rest > 0 then out:extend(shapes({ pandoc.Para(rest) })) end
    elseif block.t == 'Figure' then
      -- A figure of more than one block, as a ::: figure div makes one,
      -- which the writer writes as text, its images their alt text: each
      -- picture in it a figure of its own, the figure's id the first's and
      -- its caption the last's, after any of that one's own but one that
      -- repeats its alt text, which the page hides from a screen reader.
      local inner = shapes(block.content)
      local figures = {}
      for _, b in ipairs(inner) do
        if b.t == 'Figure' then table.insert(figures, b) end
      end
      if #figures == 0 then
        out:insert(block)
      else
        if block.identifier ~= '' and figures[1].identifier == '' then
          figures[1].identifier = block.identifier
        end
        local caption = pandoc.utils.blocks_to_inlines(block.caption.long)
        local _, img = opening_image(figures[#figures].content[1])
        local facts = img and record.pictures[img.title:sub(#PICTURE + 1)]
        if #caption > 0 and img and facts then
          if #img.caption > 0 and not facts.repeats then
            img.caption:insert(pandoc.LineBreak())
            img.caption:extend(caption)
          else
            img.caption = caption
          end
          facts.caption = true
          facts.repeats = squeezed(stringify(img.caption)) == facts.alt
        end
        out:extend(inner)
      end
    elseif opening_image(block) then
      local first, img = opening_image(block)
      picture(img, nil)
      out:insert(pandoc.Figure(pandoc.Plain({ first })))
      local rest = rest_of(block.content)
      if #rest > 0 then out:extend(shapes({ pandoc.Para(rest) })) end
    elseif block.t == 'Div' and block.classes:includes('columns') then
      block.content = block.content:map(function(column)
        if column.t == 'Div' and column.classes:includes('column') then
          column.content = shapes(column.content)
        end
        return column
      end)
      out:insert(block)
    else
      out:insert(block)
    end
  end
  return out
end

-- A slide's blocks as the writer cuts them into slides (splitBlocks): a
-- second table, or a table after a picture, begins one, and a slide's
-- columns, with the notes after them, are one of their own. Pictures (as
-- shapes() leaves them, figures) are cut too, with own: before a picture
-- on a slide with a picture or a table, and after a picture. A heading
-- of the slide level is a slide's first block; a column has none.
local function cut(blocks, own)
  local splits, current, closing = {}, {}, false
  local function flush()
    if #current > 0 then table.insert(splits, current) end
    current, closing = {}, false
  end
  local function heading_alone()
    return #current == 1 and current[1].t == 'Header'
      and (LEVEL == 0 or current[1].level == LEVEL)
  end
  local function holds_shape()
    for _, b in ipairs(current) do
      if is_shape(b) then return true end
    end
    return false
  end
  -- A heading of the slide level and nothing after it but notes.
  local function heading_and_notes()
    if #current < 2 or current[1].t ~= 'Header'
        or not (LEVEL == 0 or current[1].level == LEVEL) then
      return false
    end
    for k = 2, #current do
      if not is_notes(current[k]) then return false end
    end
    return true
  end
  local function after_picture()
    for k = #current, 1, -1 do
      if not is_notes(current[k]) then return is_picture(current[k]) end
    end
    return false
  end
  for _, block in ipairs(blocks) do
    if is_notes(block) then
      table.insert(current, block)
    else
      if closing or block.t == 'HorizontalRule'
          or (block.t == 'Header' and LEVEL and LEVEL > 0 and block.level <= LEVEL)
          or (own and (after_picture() or (is_picture(block) and holds_shape())))
          or (block.t == 'Table' and not heading_alone() and holds_shape()) then
        flush()
      end
      if block.t == 'Div' and block.classes:includes('columns') and own
          and heading_and_notes() then
        -- Notes between a slide's heading and its columns, which would
        -- leave the heading a slide of its own: after the columns, where
        -- the writer keeps them with the slide.
        local notes = { table.unpack(current, 2) }
        current = { current[1], block }
        for _, n in ipairs(notes) do table.insert(current, n) end
        closing = true
      elseif block.t == 'Div' and block.classes:includes('columns') then
        if not heading_alone() then flush() end
        table.insert(current, block)
        closing = true
      elseif block.t ~= 'HorizontalRule' then
        table.insert(current, block)
      end
    end
  end
  flush()
  return splits
end

-- Every identifier the deck uses, for a new one to be unlike them.
local used = {}

-- A heading for a part of a slide after its first: the slide's own, its
-- notes left out and its number added, its identifier the slide's with
-- the number, for a link to what the part holds.
local function continued(heading, number)
  local content = heading.content:walk({ Note = function() return {} end })
  content:extend({ pandoc.Space(), pandoc.Str('(' .. number .. ')') })
  local id = ''
  if heading.identifier ~= '' then
    id = heading.identifier .. '-' .. number
    while used[id] do id = id .. '-' .. number end
    used[id] = true
  end
  return pandoc.Header(heading.level, content, pandoc.Attr(id))
end

-- Whether a column holds text and then a picture or a table, after it.
local function text_then_shape(blocks)
  local text, shape = false, false
  for _, b in ipairs(blocks) do
    if is_shape(b) then shape = true elseif not shape then text = true end
  end
  return text and shape
end

-- What a slide's columns hold after where the writer cuts them, which it
-- leaves out: a column's first part is all it shows of it, unless the
-- slide is a comparison, whose columns it shows whole, two columns of
-- which one holds text and then a picture or a table (bodyBlocksToSlide).
-- Columns past the second it leaves out whole, and logs.
local function count_columns(block)
  local columns = {}
  for _, column in ipairs(block.content) do
    if column.t == 'Div' and column.classes:includes('column') then
      table.insert(columns, column)
    end
  end
  if #columns >= 2 and (text_then_shape(columns[1].content)
                        or text_then_shape(columns[2].content)) then
    return
  end
  for k = 1, math.min(#columns, 2) do
    local splits = cut(columns[k].content, false)
    for n = 2, #splits do
      for _, b in ipairs(splits[n]) do
        if not is_notes(b) then record.column_blocks = record.column_blocks + 1 end
      end
    end
  end
end

-- The deck's blocks with each slide cut where the writer would cut it or
-- place one shape over another (cut), each part after the first titled as
-- the slide is, and begun with a horizontal rule when no heading begins a
-- slide (a slide level of 0) or the slide has no title.
local function restructure(blocks)
  local out, segment = pandoc.Blocks({}), {}
  local function finish_segment()
    if #segment == 0 then return end
    local first = segment[1]
    local title = first.t == 'Header' and (LEVEL == 0 or first.level == LEVEL) and first or nil
    local splits = cut(segment, true)
    if #splits > 1 then
      record.cut = record.cut + 1
      record.added = record.added + #splits - 1
    end
    for k, split in ipairs(splits) do
      if k > 1 then
        if LEVEL == 0 or not title then out:insert(pandoc.HorizontalRule()) end
        if title then
          out:insert(continued(title, k))
          record.continued = record.continued + 1
        end
      end
      out:extend(split)
    end
    segment = {}
  end
  for _, block in ipairs(blocks) do
    if block.t == 'Div' and block.classes:includes('columns') then count_columns(block) end
    if block.t == 'HorizontalRule' then
      finish_segment()
      out:insert(block)
    elseif block.t == 'Header' and LEVEL > 0 and block.level <= LEVEL then
      finish_segment()
      table.insert(segment, block)
      if block.level < LEVEL then finish_segment() end
    else
      table.insert(segment, block)
    end
  end
  finish_segment()
  return out
end

-- A table's first cell given its marker.
local function mark_table(tbl)
  tables = tables + 1
  local first_column = false
  for _, body in ipairs(tbl.bodies) do
    if (body.row_head_columns or 0) > 0 then first_column = true end
  end
  record.tables[tostring(tables)] = { first_column = first_column }
  local marker = pandoc.Str(TABLE_OPEN .. tables .. TABLE_CLOSE)
  local rows = #tbl.head.rows > 0 and tbl.head.rows or nil
  if rows == nil then
    for _, body in ipairs(tbl.bodies) do
      if #body.head > 0 then rows = body.head break end
      if #body.body > 0 then rows = body.body break end
    end
  end
  local cell = rows and rows[1] and rows[1].cells[1]
  if cell == nil then return tbl end
  local contents = cell.contents
  local first = contents[1]
  if first and (first.t == 'Plain' or first.t == 'Para') then
    first.content:insert(1, marker)
  else
    contents:insert(1, pandoc.Plain({ marker }))
  end
  cell.contents = contents
  return tbl
end

-- The slides as the deck cuts them: at a heading of the slide level or
-- above, a section's heading a slide of its own, and at a horizontal
-- rule; no heading cuts at a slide level of 0.
local function slides_of(blocks)
  local found, current = {}, {}
  local function close()
    if #current > 0 then table.insert(found, current) end
    current = {}
  end
  for _, block in ipairs(blocks) do
    if block.t == 'HorizontalRule' then
      close()
    elseif block.t == 'Header' and LEVEL > 0 and block.level <= LEVEL then
      close()
      table.insert(current, block)
      if block.level < LEVEL then close() end
    else
      table.insert(current, block)
    end
  end
  close()
  return found
end

-- Each link to a place on a slide pointed at a heading on its slide, the
-- writer's only anchors.
local function retarget(doc)
  local headings, slide_of = {}, {}
  for _, slide in ipairs(slides_of(doc.blocks)) do
    local anchor, ids = nil, {}
    pandoc.Blocks(slide):walk({
      traverse = 'topdown',
      Div = function(div)
        if is_notes(div) then return div, false end
      end,
      Header = function(h)
        if h.identifier ~= '' then
          headings[h.identifier] = true
          anchor = anchor or h.identifier
        end
      end,
    })
    local function note(element)
      if element.identifier and element.identifier ~= '' then
        table.insert(ids, element.identifier)
      end
    end
    pandoc.Blocks(slide):walk({
      Div = note, Span = note, Figure = note, Table = note, CodeBlock = note,
      Code = note, Image = note, Link = note,
    })
    for _, id in ipairs(ids) do slide_of[id] = anchor or false end
  end
  return doc:walk({
    Link = function(link)
      local id = link.target:match('^#(.+)$')
      if not id or headings[id] then return nil end
      if slide_of[id] then
        record.retargeted = record.retargeted + 1
        link.target = '#' .. slide_of[id]
        return link
      end
      record.unlinked = record.unlinked + 1
    end,
  })
end

-- A div's identifier kept when the div is unwrapped, for a link to it to
-- find its slide: on the image a paragraph opens with, which a span before
-- it would make no picture; on an empty span at the head of its first
-- other paragraph, which the writer writes nothing for; or on its first
-- block with room for one.
local function keep_id(div)
  if div.identifier == '' then return end
  for _, block in ipairs(div.content) do
    local _, img = opening_image(block)
    if img then
      if img.identifier == '' then
        img.identifier = div.identifier
        return
      end
    elseif block.t == 'Para' or block.t == 'Plain' then
      block.content:insert(1, pandoc.Span({}, pandoc.Attr(div.identifier)))
      return
    elseif block.identifier == '' then
      block.identifier = div.identifier
      return
    end
  end
end

-- A metadata value as a list of its entries.
local function entries(value)
  if value == nil then return pandoc.List({}) end
  if pandoc.utils.type(value) == 'List' then return pandoc.List(value) end
  return pandoc.List({ value })
end

function Pandoc(doc)
  local meta = doc.meta
  if meta.institute ~= nil then
    local authors = entries(meta.author)
    record.creator = table.concat(authors:map(function(a) return squeezed(stringify(a)) end), '; ')
    authors:extend(entries(meta.institute))
    meta.author = authors
    meta.institute = nil
    record.institute = true
  end
  if meta['title-meta'] ~= nil then
    record.core_title = squeezed(stringify(meta['title-meta']))
    meta['title-meta'] = nil
  end
  if OMIT_NOTES and meta.notes ~= nil then
    meta.notes = nil
    record.notes = record.notes + 1
  end
  doc.meta = meta
  doc = doc:walk({
    Div = function(div)
      if is_notes(div) then
        if OMIT_NOTES then
          record.notes = record.notes + 1
          return {}
        end
        -- The writer takes a div for notes only when notes is its one
        -- class (isNotesDiv); one with another went on the slide.
        if #div.classes ~= 1 then
          div.classes = pandoc.List({ 'notes' })
          return div
        end
        return nil
      end
      if kept(div) then return nil end
      if div.attributes.lang then record.languages = record.languages + 1 end
      keep_id(div)
      return div.content
    end,
  })
  doc = doc:walk({
    Blocks = function(blocks)
      local out = pandoc.Blocks({})
      for _, block in ipairs(blocks) do
        if is_pause(block) then
          record.pauses = record.pauses + 1
        else
          out:insert(block)
        end
      end
      return out
    end,
  })
  -- Display equations in a slide's text, speaker notes, tables, and
  -- figures aside.
  doc = doc:walk({
    traverse = 'topdown',
    Div = function(div)
      if is_notes(div) then return div, false end
    end,
    Table = function(tbl) return tbl, false end,
    Figure = function(fig) return fig, false end,
    Blocks = space_displays,
  })
  doc.blocks = shapes(doc.blocks)
  if LEVEL then
    doc:walk({
      Block = function(block)
        if block.identifier and block.identifier ~= '' then used[block.identifier] = true end
      end,
      Inline = function(inline)
        if inline.identifier and inline.identifier ~= '' then used[inline.identifier] = true end
      end,
    })
    doc.blocks = restructure(doc.blocks)
    doc = retarget(doc)
  end
  -- Tables, the images left in lines of text, and the passages in other
  -- languages, speaker notes aside.
  doc.blocks = doc.blocks:walk({
    traverse = 'topdown',
    Div = function(div)
      if is_notes(div) then return div, false end
    end,
    Table = mark_table,
    Span = function(span)
      if span.attributes.lang then record.languages = record.languages + 1 end
    end,
    Image = function(img)
      if img.title:sub(1, #PICTURE) ~= PICTURE then
        record.inline_images = record.inline_images + 1
      end
    end,
  })
  if RECORD and RECORD ~= '' then
    local fh = io.open(RECORD, 'w')
    if fh then
      fh:write(pandoc.json.encode(record))
      fh:close()
    end
  end
  return doc
end
