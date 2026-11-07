-- target-blocks.lua -- a passage for some editions, and the title block
-- switch. Runs at render time, once per target, with TARGET_NAME set to
-- the target's name and TITLE_BLOCK to "on" or "off".
--
-- A Div or Span with a targets attribute names the targets it is for:
--   ::: {targets="epub print"}   kept for epub and print, dropped elsewhere
--   ::: {targets="!epub"}        kept for every target but epub
-- A kept passage is unwrapped; the attribute never reaches the output.
--
-- A Markdown or AsciiDoc target's file ends with the footer setting, in
-- a div of class oer-footer (FOOTER_JSON, which convert.py sets).
--
-- A page's language, page-language in its metadata, is its lang in every
-- writer but those two, whose lang convert.py has set already.
--
-- A Div or Span with class embed is an <iframe> html-source.lua read,
-- its attributes the frame's and its content a link to what it framed.
-- An HTML writer gets the <iframe> back; every other writer gets the
-- link, since an EPUB reading system can't be relied on to load a remote
-- frame and a printed page can't at all. The Markdown writer is the
-- exception: it keeps the Div, attributes and all, so a Markdown source
-- holds the decision and reads back to it.
--
-- A formula whose TeX opens with \displaystyle is in display style in the
-- MathML of a page, an EPUB, and a deck's reveal.js presentation too, but
-- in a heading, whose text the writer reads.
--
-- A formula in a picture's description is its text there, for every writer
-- but Markdown's: the writers make the description the picture's alt text,
-- and gave a formula its TeX in it.
--
-- A note in a link's text goes after the link, for every writer but
-- those two: a page's note in a link was an anchor in an anchor. And two
-- notes in a row get a comma between their marks, "1,2", not "12".
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

-- What a target loses in the writing, for the run's fidelity report
-- (fidelity.csv): convert.py names a file in FIDELITY_FOUND, and each
-- change below that loses something is a row there, its kind and a
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

local TARGET = os.getenv('TARGET_NAME') or ''
local TITLE_BLOCK = (os.getenv('TITLE_BLOCK') or 'on') ~= 'off'
local TITLE_WRITER = os.getenv('TITLE_WRITER') or ''
-- convert.py's LANGUAGE_KEY, and the writers whose files are sources again.
local LANGUAGE_KEY = 'page-language'
local SOURCE_WRITERS = { markdown = true, asciidoc = true }

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

-- An image on another server can't be in an EPUB: the package holds its
-- images, and a reading system won't fetch one (epubcheck: RSC-007). So
-- for an EPUB it's a link to the image, named by its alt text; every
-- other writer keeps the image. The same decision as for a frame. Each
-- link so made is kept by its address and its text, for hidden_caption
-- to tell it from an author's link in a figure.
local remote_links = {}
local function remote_image(img)
  if not FORMAT:match('epub') then return nil end
  if not (img.src:match('^%a[%w+.-]*://') or img.src:match('^//')) then
    return nil
  end
  local text = pandoc.utils.stringify(img.caption)
  if text == '' then
    text = 'Image at ' .. (img.src:match('^%a*:?//([^/?#]+)') or img.src)
  end
  lost('remote-image', img.src)
  remote_links[img.src .. '\0' .. text] = true
  return pandoc.Link(text, img.src)
end

-- A link to a local file that isn't a page -- the PDF or Word file a
-- course page offers -- can't be in an EPUB either: a reading system
-- follows links only among the book's own content documents, so the
-- file would be a dead link (epubcheck: RSC-007) or, packaged, a
-- hyperlink to a resource outside the spine. Its text stays, so the
-- sentence still reads, marked with the file it named, which the output
-- check reports.
local function local_file_link(link)
  if not FORMAT:match('epub') then return nil end
  local target = link.target
  if target:match('^%a[%w+.-]*:') or target:match('^//')
      or target:match('^#') then
    return nil
  end
  local path = target:match('^([^#?]*)')
  if path == '' or not path:match('%.%w+$')
      or path:lower():match('%.x?html?$') then
    return nil
  end
  -- Named as a person reads it, not percent-encoded.
  local name = path:gsub('%%(%x%x)', function(hex)
    return string.char(tonumber(hex, 16))
  end)
  lost('file-link', name)
  return pandoc.Span(link.content,
    pandoc.Attr('', { 'file-link' }, { { 'data-file', name } }))
end

-- A note in a link's text goes after the link, the notes in the order the
-- link held them. An HTML writer writes a note's mark as a link of its
-- own, inside the link's, an anchor in an anchor, which HTML doesn't allow
-- (Pandoc writes [x[^1]](u) so, Writers/HTML.hs, 3.12.1), and LaTeX's
-- tagging set the mark, a link, and the note's text inside the link's
-- structure element, the note read as part of the link. Once a span or a
-- div meant for another target is gone (resolve), with any note in it.
-- Not for a source writer, Markdown's or AsciiDoc's, whose file keeps what
-- the author wrote. A link whose text was its note alone is gone already,
-- the note kept (figures-and-tables.lua's Link).
local function notes_after(link)
  if SOURCE_WRITERS[FORMAT] then return nil end
  local notes = pandoc.List()
  local content = link.content:walk({
    Note = function(note)
      notes:insert(note)
      return {}
    end,
  })
  if #notes == 0 then return nil end
  link.content = content
  local out = pandoc.Inlines({ link })
  out:extend(notes)
  return out
end

-- Two notes in a row get a comma between their marks, set as the marks
-- are, "1,2", where they read as one number, "12": several notes in one
-- link's text, which notes_after puts in a row after it, and two an
-- author wrote together. LaTeX's footmisc package sets them so with its
-- multiple option. Not for a source writer, whose file keeps what the
-- author wrote. A space between two notes keeps their marks apart
-- already. Only in the body's text, a paragraph's, a line block's, a
-- table's cell's, a definition's, a term's, what a figure holds: not in a
-- heading or a caption, whose words are a title, a contents entry, a
-- bookmark, or a list of figures' entry too, where the notes are taken out
-- and a comma would have stayed ("Sets,"; a review). Nor in a picture's
-- description, which isn't text with marks. And not in a term for LaTeX,
-- where pdf-target.lua's term_notes moves a term's notes to the head of
-- its definition, a comma between them, so none stays behind in the term.
local NOTE_HOLDERS = { Emph = true, Strong = true, Underline = true, Strikeout = true,
                       SmallCaps = true, Superscript = true, Subscript = true, Span = true,
                       Quoted = true }
local TERMS_MOVED = { latex = true, beamer = true }

local function comma_notes(inlines)
  local out, changed = pandoc.Inlines({}), false
  for i, inline in ipairs(inlines) do
    if inline.t == 'Note' and i > 1 and inlines[i - 1].t == 'Note' then
      out:insert(pandoc.Superscript({ pandoc.Str(',') }))
      changed = true
    elseif NOTE_HOLDERS[inline.t] then
      local inner = comma_notes(inline.content)
      if inner then
        inline.content = inner
        changed = true
      end
    end
    out:insert(inline)
  end
  if changed then return out end
  return nil
end

local separate_notes = {}
if not SOURCE_WRITERS[FORMAT] then
  local function text(block)
    local content = comma_notes(block.content)
    if content then
      block.content = content
      return block
    end
  end
  local function lines(block)
    local content, changed = pandoc.List({}), false
    for _, line in ipairs(block.content) do
      local separated = comma_notes(line)
      changed = changed or separated ~= nil
      content:insert(separated or line)
    end
    if changed then
      block.content = content
      return block
    end
  end
  -- A table's cells, each as the body is, its caption left alone; each
  -- part read, changed, and assigned back, as a table's head and bodies
  -- are copies when read (PANDOC-NOTES).
  local function in_rows(rows)
    for _, row in ipairs(rows) do
      local cells = row.cells
      for _, cell in ipairs(cells) do
        cell.contents = cell.contents:walk(separate_notes)
      end
      row.cells = cells
    end
    return rows
  end
  separate_notes = {
    traverse = 'topdown',
    Figure = function(fig)
      fig.content = fig.content:walk(separate_notes)
      return fig, false
    end,
    Table = function(tbl)
      local head, bodies, foot = tbl.head, tbl.bodies, tbl.foot
      head.rows = in_rows(head.rows)
      for _, body in ipairs(bodies) do
        body.head = in_rows(body.head)
        body.body = in_rows(body.body)
      end
      foot.rows = in_rows(foot.rows)
      tbl.head, tbl.bodies, tbl.foot = head, bodies, foot
      return tbl, false
    end,
    DefinitionList = function(list)
      local items = pandoc.List({})
      for _, item in ipairs(list.content) do
        local term = item[1]
        if not TERMS_MOVED[FORMAT] then
          term = comma_notes(term) or term
        end
        local definitions = pandoc.List({})
        for _, blocks in ipairs(item[2]) do
          definitions:insert(pandoc.Blocks(blocks):walk(separate_notes))
        end
        items:insert({ term, definitions })
      end
      list.content = items
      return list, false
    end,
    Para = text,
    Plain = text,
    LineBlock = lines,
  }
end

local function escape(value)
  return (value:gsub('&', '&amp;'):gsub('"', '&quot;'):gsub('<', '&lt;'))
end

local function embed(el, block)
  -- A source target keeps the frame, for its own filter to write.
  if FORMAT:match('markdown') or FORMAT:match('asciidoc') then return nil end
  if not FORMAT:match('html') or FORMAT:match('epub') then
    lost('frame', el.attributes['title'] or el.attributes['src'] or '')
    return el.content
  end
  local parts = { '<iframe' }
  for _, pair in ipairs(el.attributes) do
    parts[#parts + 1] = (' %s="%s"'):format(pair[1], escape(pair[2]))
  end
  local markup = table.concat(parts) .. '></iframe>'
  if block then return pandoc.RawBlock('html', markup) end
  return pandoc.RawInline('html', markup)
end

-- A formula in display style, its TeX opening with \displaystyle (as
-- html-source.lua makes a formula a page marks so): for a page, an EPUB, or
-- a reveal.js presentation, each written with MathML, its MathML in an
-- <mstyle displaystyle="true">, which texmath's writer doesn't write,
-- reading TeX's \displaystyle as nothing, and laid out as texmath lays out
-- a display, a sum's limits under and over it and a limit's under it, as
-- TeX's display style sets them, where in a formula in text it sets them
-- as scripts; in the line still (display="inline"). The rest is written as
-- the page's writer writes a formula, its TeX, \displaystyle and all, its
-- annotation, which the HTML reader reads in its place: a page read again
-- has the formula it was written from.
local DISPLAYED = '^%s*\\displaystyle%f[^%a]'
local function display_style(math_)
  if math_.mathtype ~= 'InlineMath' or not math_.text:match(DISPLAYED) then
    return nil
  end
  local written = pandoc.write(
    pandoc.Pandoc({ pandoc.Plain({ pandoc.Math('DisplayMath', math_.text) }) }), 'html5',
    { html_math_method = 'mathml', prefer_ascii = PANDOC_WRITER_OPTIONS.prefer_ascii })
  local open, body, annotation = written:match(
    '^%s*(<math[^>]*>%s*<semantics>)(.-)(<annotation encoding="application/x%-tex">.*</math>)%s*$')
  if not open or not open:find('display="block"', 1, true) then return nil end
  return pandoc.RawInline('html', open:gsub('display="block"', 'display="inline"', 1)
    .. '<mstyle displaystyle="true">' .. body .. '</mstyle>' .. annotation)
end

-- A formula in a picture's description as its text there, "A square of
-- side x²" for ![A square of side $x^2$](sq.png), as a title has it
-- (math-text.lua's title_text). The writers make the description text for
-- the picture's alt text, a page's, an EPUB's, and a reveal.js
-- presentation's alt, a PDF's /Alt, a Word file's and a PowerPoint file's
-- description, and AsciiDoc's alt, a formula its TeX there ("x^2", as
-- Pandoc's stringify gives it), which a screen reader read as written; a
-- link the EPUB makes of an image on another server is named so too
-- (remote_image). Not for Markdown, whose writer keeps the formula, the
-- description being a figure's caption too where they're the same, and
-- read again; AsciiDoc's alt and a Word file's description hold text alone,
-- and reading the file again finds the text, a loss (alt-formula).
--
-- Pandoc's HTML writer hides a figure's caption from a screen reader where
-- it says what the figure's one picture's alt text says, comparing the
-- caption's text with the alt text (captionIsAlt, Writers/HTML.hs, 3.13),
-- as a Markdown figure's image, ![caption](file), has its caption for alt
-- text. With the formula's text in the alt text and its TeX in the
-- caption's, the writer would show the caption to a screen reader beside
-- the alt text, the words said twice, so the caption's words are hidden in
-- a span (aria-hidden) where, each formula its text, they're the alt text's;
-- and so beside the link an EPUB makes of a picture on another server,
-- named by its alt text, beside which the writer hides no caption, a
-- formula in it or not (hidden_captions, once the link is made); but for a
-- caption with a link or a note, whose mark is a link, which a screen
-- reader can't reach hidden (axe-core's aria-hidden-focus).
local mathtext = dofile(pandoc.path.join({ pandoc.path.directory(PANDOC_SCRIPT_FILE),
                                           'math-text.lua' }))

local function holds(content, kinds)
  local found = false
  local walker = {
    Inline = function(inline)
      if kinds[inline.t] then found = true end
    end,
  }
  if pandoc.utils.type(content) == 'Blocks' then content:walk(walker)
  else pandoc.Inlines(content):walk(walker) end
  return found
end

local FORMULA = { Math = true }
local REACHED = { Link = true, Note = true }

local function formula_alts(doc)
  if FORMAT == 'markdown' then return nil end
  doc.blocks = doc.blocks:walk({
    Image = function(img)
      if not holds(img.caption, FORMULA) then return nil end
      img.caption = mathtext.texted(img.caption)
      if FORMAT == 'asciidoc' or FORMAT == 'docx' then
        lost('alt-formula', pandoc.utils.stringify(img.caption))
      end
      return img
    end,
  })
  return doc
end

local function hidden_caption(fig)
  local body = fig.content
  if #body ~= 1 or body[1].t ~= 'Plain' or #body[1].content ~= 1 then return nil end
  local only, caption, alt = body[1].content[1], fig.caption, nil
  if only.t == 'Image' then
    -- A caption with no formula the writer hides itself; beside a picture
    -- with an alt attribute, it compares the caption with that.
    if only.attributes.alt ~= nil or not holds(caption.long, FORMULA) then return nil end
    alt = pandoc.utils.stringify(only.caption)
  elseif only.t == 'Link'
      and remote_links[only.target .. '\0' .. pandoc.utils.stringify(only.content)] then
    -- An EPUB's link for a picture on another server, named by its alt
    -- text, beside which the writer hides no caption, a formula in it or
    -- not, as it would beside the picture.
    alt = pandoc.utils.stringify(only.content)
  else
    return nil
  end
  if pandoc.utils.stringify(mathtext.texted(caption.long)) ~= alt then return nil end
  for _, block in ipairs(caption.long) do
    if (block.t ~= 'Plain' and block.t ~= 'Para') or holds(block.content, REACHED) then
      return nil
    end
  end
  caption.long = caption.long:map(function(block)
    block.content = { pandoc.Span(block.content, pandoc.Attr('', {}, { { 'aria-hidden', 'true' } })) }
    return block
  end)
  fig.caption = caption
  return fig
end

local function hidden_captions(doc)
  if not (FORMAT:match('html') or FORMAT:match('epub') or FORMAT == 'revealjs') then
    return nil
  end
  doc.blocks = doc.blocks:walk({ Figure = hidden_caption })
  return doc
end

-- Each such formula in the body, but in a heading, whose text the writer
-- reads, a raw formula giving it none: an EPUB's contents and its
-- chapter's title. There the formula keeps its TeX, \displaystyle and all,
-- in text style. A picture's description holds none by now, each its text
-- there (formula_alts).
local function display_styles(doc)
  if not (FORMAT:match('html') or FORMAT:match('epub') or FORMAT == 'revealjs') then
    return nil
  end
  doc.blocks = doc.blocks:walk({
    traverse = 'topdown',
    Header = function(h) return h, false end,
    Math = display_style,
  })
  return doc
end

local function resolve(el)
  local spec = el.attributes['targets']
  if spec == nil then
    if el.classes:includes('embed') then
      return embed(el, el.t == 'Div')
    end
    return nil
  end
  if not wanted(spec) then return {} end
  return el.content
end

-- A page with no title is named by its own name in <title>, not by
-- the intermediate's file name, which is what Pandoc falls back to
-- ("costs.filtered").
local function own_name()
  local name = (PANDOC_STATE.input_files[1] or ''):match('([^/\\]+)$') or ''
  return (name:gsub('%.json$', ''):gsub('%.filtered$', ''))
end

-- A title's words with each formula as its text, as title-formulas.lua
-- noted it (texts, from formula-texts), for a page's <title>, where
-- Pandoc's writer gives a formula's TeX ("The x^2 law"); a formula it
-- didn't note is its TeX still.
local function title_text(title, texts)
  if pandoc.utils.type(title) ~= 'Inlines' then return pandoc.utils.stringify(title) end
  return pandoc.utils.stringify(title:walk({
    Math = function(math_)
      local text = texts and texts[math_.text]
      if text ~= nil then return pandoc.Str(pandoc.utils.stringify(text)) end
    end,
  }))
end

-- Whether a title holds a formula.
local function holds_formula(title)
  local found = false
  if pandoc.utils.type(title) == 'Inlines' then
    title:walk({ Math = function() found = true end })
  end
  return found
end

-- A page whose title is its own H1 (the filter marked it title-heading,
-- having taken the heading out of the body so the split, the contents,
-- and the numbering find the title in one place) gets the heading back as
-- its first block, its id with it. HTML then names the page with
-- pagetitle, for <title>, and has no title block to say it twice; Word
-- gets a Heading 1 rather than a Title paragraph (docxtarget.py puts the
-- title in the file's properties); Markdown and AsciiDoc keep the title in
-- their metadata as well. A page with a subtitle, date, or abstract keeps
-- the HTML title block, which shows them under the title.
local function title_heading(doc)
  local meta = doc.meta
  local marked = meta['title-heading']
  meta['title-heading'] = nil
  local id = meta['title-id'] and pandoc.utils.stringify(meta['title-id']) or ''
  meta['title-id'] = nil
  meta['title-index'] = nil
  -- What the page is (page-type, from the heading's epub:type or class)
  -- goes back on the heading in Markdown, as Pandoc's own syntax for it;
  -- an HTML page, which isn't XHTML, can't carry epub:type.
  local page_type = meta['page-type'] and pandoc.utils.stringify(meta['page-type']) or ''
  meta['page-type'] = nil
  -- A deck's slide level, which decks.py recorded when the deck was read,
  -- and the PDF's writer is given as an option.
  meta['deck-slide-level'] = nil
  -- The formulas of the headings and the title as text, which the split
  -- and the EPUB's titles read (title-formulas.lua), and <title> below.
  local texts = meta['formula-texts']
  meta['formula-texts'] = nil
  -- The page's language, which convert.py decided once for every target
  -- (lib/languages.py): the page's lang, in place of the book's that -M
  -- gave, for every writer but Markdown's and AsciiDoc's, whose lang is
  -- what the author decided, set in the intermediate already.
  local language = meta[LANGUAGE_KEY] and pandoc.utils.stringify(meta[LANGUAGE_KEY]) or ''
  meta[LANGUAGE_KEY] = nil
  if language ~= '' and not SOURCE_WRITERS[FORMAT] then
    meta.lang = pandoc.MetaString(language)
  end
  -- A declared title with a formula, which Pandoc's writers give the
  -- formula's TeX where they make the title text ("The x^2 law"): its
  -- formulas as text in <title>, where the HTML writer shows the title in
  -- the title block, and a deck's reveal.js presentation's; and in a
  -- deck's PDF's properties and its PowerPoint file's, title-meta, which
  -- the PDF's template gives hyperref and deck-pptx.lua takes for the
  -- file's title.
  if holds_formula(meta.title) then
    local text = pandoc.MetaString(title_text(meta.title, texts))
    if (TITLE_WRITER == 'html' or FORMAT == 'revealjs') and meta.pagetitle == nil then
      meta.pagetitle = text
    elseif (FORMAT == 'beamer' or FORMAT == 'pptx') and meta['title-meta'] == nil then
      meta['title-meta'] = text
    end
  end
  if not marked or meta.title == nil or TITLE_WRITER == '' then return doc end
  if TITLE_WRITER == 'html' and TITLE_BLOCK
      and (meta.subtitle or meta.date or meta.abstract) then
    -- The title block shows the title, the subtitle, date, and abstract
    -- under it, and the heading isn't written; where the title is the
    -- heading's words, with a formula among them, it shows the heading,
    -- the formula as a formula, where it had shown the title's text
    -- ("Limits a/b"), and <title> has the text.
    if holds_formula(marked) and title_text(marked, texts) == title_text(meta.title, texts) then
      meta.pagetitle = pandoc.MetaString(title_text(meta.title, texts))
      meta.title = pandoc.MetaInlines(marked)
    end
    return doc
  end
  local content = marked
  if pandoc.utils.type(content) ~= 'Inlines' then
    content = pandoc.Inlines(pandoc.utils.stringify(content))
  end
  local attributes = {}
  if TITLE_WRITER == 'markdown' and page_type ~= '' then
    attributes = { ['epub:type'] = page_type }
  end
  doc.blocks:insert(1, pandoc.Header(1, content, pandoc.Attr(id, {}, attributes)))
  if TITLE_WRITER == 'html' then
    meta.pagetitle = pandoc.MetaString(title_text(meta.title, texts))
    meta.title = nil
  elseif TITLE_WRITER == 'docx' then
    meta.title = nil
  end
  return doc
end

-- A link color a source gives for its PDF (a beamer deck's linkcolor:
-- blue) reaches the HTML page too, where Pandoc's stylesheet (3.12) writes
-- light-dark(blue, inherit) for it, which isn't CSS, inherit being no
-- color: the Nu checker's CSS checker stopped on it. currentcolor is one,
-- and does in dark mode what inherit would have, so a link takes the text's
-- own color there, underlined, as with no link color at all.
local function link_color(meta)
  if FORMAT:match('html') and not FORMAT:match('epub')
      and meta.linkcolor ~= nil and meta.linkcolordark == nil then
    meta.linkcolordark = pandoc.MetaString('currentcolor')
  end
end

local function drop_title_block(meta)
  link_color(meta)
  if meta.title == nil and meta.pagetitle == nil and own_name() ~= '' then
    meta.pagetitle = pandoc.MetaString(own_name())
    if TITLE_BLOCK then return meta end
  end
  if TITLE_BLOCK then return meta end
  for _, key in ipairs({ 'subtitle', 'date', 'abstract', 'include-before',
                         'include-after' }) do
    meta[key] = nil
  end
  return meta
end

-- The footer setting at the end of a Markdown or AsciiDoc target's file,
-- from the document pagefooter.py writes: added before any other filter
-- runs, so the file's own filters write it as they write the page
-- (markdown-source.lua makes it an open block in AsciiDoc), and reading
-- the file back takes it out again (figures-and-tables.lua).
local FOOTER_JSON = os.getenv('FOOTER_JSON') or ''
local function add_footer(doc)
  if FOOTER_JSON == '' then return nil end
  local fh = io.open(FOOTER_JSON, 'r')
  if not fh then return nil end
  local blocks = pandoc.read(fh:read('a'), 'json').blocks
  fh:close()
  if #blocks == 0 then return nil end
  doc.blocks:insert(pandoc.Div(blocks, pandoc.Attr('', { 'oer-footer' })))
  return doc
end

return {
  { Pandoc = add_footer },
  -- A passage for other targets is gone before anything is made of what
  -- it holds: in one pass, Pandoc gives each image and link to its
  -- function before the div or span around it, and an EPUB reported a
  -- picture on another server and a link to a file it left out.
  { Div = resolve, Span = resolve },
  -- A formula in a picture's description is its text before an EPUB names
  -- a link by the description, and a caption is compared with the alt
  -- text, or with that link's text, once the link is made, and before a
  -- formula in display style is raw HTML.
  { Pandoc = formula_alts },
  { Image = remote_image, Link = local_file_link },
  { Pandoc = hidden_captions },
  { Link = notes_after },
  separate_notes,
  { Pandoc = display_styles },
  { Pandoc = title_heading },
  { Meta = drop_title_block },
}
