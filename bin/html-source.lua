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
  - A header row written inside <tbody>, which is where Pressbooks and
    most editors put one, is read as that body's own head rows
    (pTableBody's bodyheads) and would be written back inside the
    body. When the table has no head and its first body opens with
    such rows, they are the table's head and are moved there.

  - A <section> or <header> is opened up and its contents stand where
    it stood. Every generator wraps a heading and what follows it in a
    <section> (Asciidoctor, Scribble, Pandoc's own --section-divs), and
    the split cuts only at headings that are not inside something, so
    a chapter-per-section book arrived as one page however it was
    declared. The reader moves a heading's id onto the section when the
    two agree (pDiv), so the id goes back on the heading; any other id
    a section had is kept as an empty anchor.
  - An empty span holding an id inside a heading (an anchor, like the
    <a name> Scribble puts in every heading) moves out of it: the id
    becomes the heading's when it has none, and an empty anchor before
    the heading otherwise. Pandoc's EPUB writer builds the navigation
    from a heading's inlines, and an empty span in a nav entry is an
    epubcheck error (11 of them in one book).
  - A page's only h1, when it sits inside wrappers (Pressbooks puts it
    in section > div.chapter > div.chapter-title-wrap), is lifted out to
    stand before them, where promote_h1_to_title can see it. Left where
    it was, the page's <title> became the title ("1.3. Information
    Systems Components -- Information Systems for Business and Beyond")
    and the chapter's own h1 a second one, on 166 of 168 pages.
  - HTML's obsolete presentational attributes (align, valign, bgcolor,
    cellpadding, hspace, and their kind) are dropped from what keeps its
    attributes: a div, a span, an image, a link, a heading, a table.
    XHTML allows them nowhere, and a stylesheet is where their work
    goes; a table cell's align the reader has already made alignment.
  - A page's title that ends with the book's own title after a separator
    ("Copyright -- Information Systems for Business and Beyond") loses the
    suffix: a site or an exporter adds the book's name to every page's
    <title>, and the book's name is the book's, not the page's. The book's
    title comes from project.yaml, which convert.py passes in BOOK_TITLE.
    Nothing is dropped from a title that is only the book's name. A
    page with an h1 of its own takes that as its title anyway.
  - Raw HTML is html-raw.lua's, which runs before this filter on a
    source and alone on a finished page.
  - An aria-describedby or aria-labelledby that names an id the page no
    longer has is dropped, the rest of its list kept. WordPress points
    every <figure> at its own <figcaption> that way, the reader keeps
    no id of a figcaption, and an ARIA reference to nothing is an error
    in every checker (118 of them in one Pressbooks book's EPUB).

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

local OBSOLETE = { align = true, valign = true, bgcolor = true,
                   background = true, cellpadding = true, cellspacing = true,
                   hspace = true, vspace = true, frame = true, rules = true,
                   clear = true, nowrap = true, char = true, charoff = true,
                   axis = true }

local function drop_obsolete(el)
  local changed = false
  local kept = {}
  for _, pair in ipairs(el.attr.attributes) do
    if OBSOLETE[pair[1]:lower()] then changed = true
    else kept[#kept + 1] = pair end
  end
  if changed then el.attr.attributes = kept end
  return changed
end


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

local function lift_body_head(tbl)
  if #tbl.head.rows > 0 then return false end
  local body = tbl.bodies[1]
  if body == nil or #body.head == 0 then return false end
  tbl.head = pandoc.TableHead(body.head, tbl.head.attr)
  body.head = {}
  return true
end

function Table(tbl)
  drop_obsolete(tbl)
  if tbl.attr.attributes[MARKER_ATTR] then return tbl end
  lift_body_head(tbl)
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

local SEPARATORS = { ' -- ', ' | ', ' \u{2013} ', ' \u{2014} ', ' - ',
                     ' \u{00B7} ' }

local function without_book_title(title)
  local book = (os.getenv('BOOK_TITLE') or ''):gsub('%s+', ' ')
    :gsub('^ ', ''):gsub(' $', '')
  if book == '' then return nil end
  title = title:gsub('%s+', ' '):gsub('^ ', ''):gsub(' $', '')
  for _, sep in ipairs(SEPARATORS) do
    local suffix = sep .. book
    if #title > #suffix
        and title:sub(-#suffix):lower() == suffix:lower() then
      local rest = title:sub(1, #title - #suffix)
      if rest:match('%S') then return rest end
    end
  end
  return nil
end

function Meta(meta)
  local changed = false
  if meta.title then
    local shorter = without_book_title(pandoc.utils.stringify(meta.title))
    if shorter then
      meta.title = pandoc.MetaString(shorter)
      changed = true
    end
  end
  for key, value in pairs(title_block_fields()) do
    if meta[key] == nil then
      meta[key] = value
      changed = true
    end
  end
  return changed and meta or nil
end


local function open_up(div)
  local blocks = pandoc.List(div.content)
  if div.identifier ~= '' then
    local first = blocks[1]
    if first and first.t == 'Header' and first.identifier == '' then
      first.identifier = div.identifier
    else
      blocks:insert(1, pandoc.Div({}, pandoc.Attr(div.identifier,
                                                  { 'anchor' })))
    end
  end
  return blocks
end

function Image(img)
  if drop_obsolete(img) then return img end
end

function Link(link)
  if drop_obsolete(link) then return link end
end

-- A heading with no text in it (an editor's leftover <h3>&nbsp;</h3>)
-- names nothing and every checker flags it; it goes, its id kept as an
-- anchor for anything that links to it. One holding an image stays.
local function blank_heading(h)
  if pandoc.utils.stringify(h.content):gsub('[%s\u{00A0}]', '') ~= '' then
    return false
  end
  local holds = false
  pandoc.Inlines(h.content):walk({
    Image = function() holds = true end,
    Math = function() holds = true end,
    Code = function() holds = true end,
    RawInline = function() holds = true end,
  })
  return not holds
end

local function empty_anchor(inline)
  return inline.t == 'Span' and inline.identifier ~= ''
    and #inline.content == 0
end

function Header(h)
  if blank_heading(h) then
    -- "section", "section-1": the reader's own id for a heading with no
    -- text, which nothing outside the page can have linked to.
    if h.identifier ~= '' and not h.identifier:match('^section%-?%d*$') then
      return pandoc.Div({}, pandoc.Attr(h.identifier, { 'anchor' }))
    end
    return {}
  end
  local ids = {}
  local kept = pandoc.Inlines({})
  for _, inline in ipairs(h.content) do
    if empty_anchor(inline) then ids[#ids + 1] = inline.identifier
    else kept:insert(inline) end
  end
  if #ids == 0 then return nil end
  h.content = kept
  local before = {}
  for _, id in ipairs(ids) do
    if h.identifier == '' then h.identifier = id
    else before[#before + 1] = pandoc.Div({}, pandoc.Attr(id, { 'anchor' })) end
  end
  before[#before + 1] = h
  return before
end

-- An href on something that isn't a link: RDFa on a license statement
-- (<span href="http://purl.org/dc/dcmitype/Text" rel="dct:type">). The
-- HTML writer passes it through, and XHTML allows it on no such element.
function Span(span)
  local changed = drop_obsolete(span)
  if span.attributes.href then
    span.attributes.href = nil
    changed = true
  end
  return changed and span or nil
end

function Div(div)
  if div.identifier == 'title-block-header' then return {} end
  if div.attributes.href then div.attributes.href = nil end
  drop_obsolete(div)
  if div.classes:includes('section') or div.classes:includes('header') then
    return open_up(div)
  end
  if div.classes:includes('table-wrapper') and #div.content == 1
      and div.content[1].t == 'Table' then
    return div.content[1]
  end
  return nil
end

-- Dangling ARIA references, as the last step: every id has to have been
-- seen, and a handler in the same table runs before the ids settle.
local IDREFS = { 'aria-describedby', 'aria-labelledby' }

local function with_attr(handler)
  local filter = {}
  for _, name in ipairs({ 'Div', 'Span', 'Header', 'Figure', 'Table', 'Link',
                          'Image', 'Code', 'CodeBlock' }) do
    filter[name] = handler
  end
  return filter
end

local function count_h1(blocks)
  local n = 0
  pandoc.Blocks(blocks):walk({ Header = function(h)
    if h.level == 1 then n = n + 1 end
  end })
  return n
end

-- Remove the first level-1 Header inside a Div, however deep; return it.
local function take_h1(div)
  for i, block in ipairs(div.content) do
    if block.t == 'Header' and block.level == 1 then
      table.remove(div.content, i)
      return block
    elseif block.t == 'Div' then
      local found = take_h1(block)
      if found then return found end
    end
  end
  return nil
end

local function lift_h1(doc)
  if count_h1(doc.blocks) ~= 1 then return end
  for i, block in ipairs(doc.blocks) do
    if block.t == 'Header' and block.level == 1 then return end
    if block.t == 'Div' and count_h1({ block }) == 1 then
      local h1 = take_h1(block)
      if h1 then doc.blocks:insert(i, h1) end
      return
    end
  end
end

function Pandoc(doc)
  lift_h1(doc)
  local ids = {}
  doc:walk(with_attr(function(el)
    if el.identifier ~= '' then ids[el.identifier] = true end
    return nil
  end))
  return doc:walk(with_attr(function(el)
    local changed = false
    for _, name in ipairs(IDREFS) do
      local value = el.attributes[name]
      if value then
        local kept = {}
        for id in value:gmatch('%S+') do
          if ids[id] then kept[#kept + 1] = id end
        end
        local joined = table.concat(kept, ' ')
        if joined ~= value then
          el.attributes[name] = (#kept > 0) and joined or nil
          changed = true
        end
      end
    end
    return changed and el or nil
  end))
end
