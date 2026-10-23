-- deck-pdf.lua -- what a deck's PDF needs beyond what the beamer writer
-- gives it for ltx-talk. Runs when lib/decks.py writes a deck with
-- Pandoc's beamer writer, after target-blocks.lua and before
-- pdf-target.lua, which writes a table inside a table's cell as LaTeX, its
-- footnotes with it, where they'd be counted here no longer;
-- DECK_SLIDE_LEVEL is the slide level decks.py gives the writer, its
-- headings renumbered so its sections are 1, 2, 3 and its slides one
-- below the deepest (decks.renumber).
--
-- Speaker notes, Pandoc's ::: notes divs, which the writer writes as
-- \note, are left out: ltx-talk 0.6.9 has no \note, and no notes pages to
-- put them on. The deck's page has them (deck-html.lua).
--
-- A passage in another language, a span or a div with a lang attribute,
-- is tagged with its language (ltx-talk.latex's \oerlang and oerlanguage),
-- where the writer would mark it for babel, which tags nothing: after the
-- footnotes are numbered, so a footnote's text set after its heading, as
-- below, is in the heading's language still.
--
-- A footnote in a slide's title keeps its mark in the title, and its
-- text goes at the head of the slide (\footnotetext, numbered as LaTeX
-- numbers the deck's footnotes, in order): ltx-talk sets the title after
-- the slide's footnotes, and a footnote there was lost. A footnote in any
-- other heading is numbered so too, its text after the heading, where it
-- had been inside it and a screen reader read it as part of it: on a
-- section's slide, after its heading, at the head of a block, and after a
-- heading in a quotation or a list. So is one in a figure's caption,
-- since LaTeX sets a caption twice and counted its mark twice, or in a
-- table, its text after the figure or the table. The template ties each
-- mark to its text, a link and a /Ref each way.
--
-- A block's title, and a heading in a quotation, a list, or a table, is a
-- heading at the level the deck's page gives it (nested_headings; the
-- template's \oerblocklevel and oerheading).
--
-- Each slide with a title gets a bookmark, under the section it's in:
-- ltx-talk bookmarks a section and not a slide, so a deck without
-- sections had no outline at all to move through.
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

local LEVEL = tonumber(os.getenv('DECK_SLIDE_LEVEL') or '') or 1

-- Characters LaTeX would read as markup, in a bookmark's text, which
-- hyperref's \pdfstringdef turns back into characters.
local SPECIALS = {
  ['\\'] = '\\textbackslash{}', ['{'] = '\\{', ['}'] = '\\}',
  ['#'] = '\\#', ['$'] = '\\$', ['%'] = '\\%', ['&'] = '\\&',
  ['_'] = '\\_', ['~'] = '\\textasciitilde{}',
  ['^'] = '\\textasciicircum{}',
}

local function tex_escape(text)
  return (text:gsub('[\\{}#%$%%&_~%^]', SPECIALS))
end

-- And hyphens and backticks, which \pdfstringdef reads as dashes (-- and
-- ---) and inverted marks (?` and !`), as TeX's text does: an empty group
-- after each hyphen and before each backtick keeps a title's own, as the
-- writer prints a title's two hyphens (-\/-), and as pdf-target.lua
-- keeps a link's description.
local function unjoined(text)
  return (text:gsub('%-', '-{}'):gsub('`', '{}`'))
end

local function notes(div)
  if div.classes:includes('notes') then
    return {}
  end
end

-- Whether a div holds a heading of the slide level or above, a slide or
-- a section, as Pandoc's slide writers find slides in divs; with any, a
-- heading of any level, which beamer makes a block if it's below.
local function holds_heading(div, any)
  for _, block in ipairs(div.content) do
    if block.t == 'Header' and (any or block.level <= LEVEL) then return true end
    if block.t == 'Div' and holds_heading(block, any) then return true end
  end
  return false
end

-- Whether a heading holds anything that's set: words, code, a formula, a
-- picture, a footnote, raw markup, in a span or any other inline or not;
-- a block whose title holds nothing, or only empty spans, has no title,
-- and no heading.
local function holds_words(inlines)
  for _, inline in ipairs(inlines) do
    local kind = inline.t
    if kind == 'Str' or kind == 'Code' or kind == 'Math' or kind == 'Image'
        or kind == 'Note' or kind == 'RawInline' then
      return true
    elseif kind ~= 'Space' and kind ~= 'SoftBreak' and kind ~= 'LineBreak'
        and inline.content and holds_words(inline.content) then
      return true
    end
  end
  return false
end

local function titled(header)
  return holds_words(header.content)
end

-- A heading in a slide at the level the deck's page gives it
-- (deck-html.lua's placed), counted from the slide's title: one below it,
-- and one more for each heading before it that it's under, in reading
-- order, columns and all, a block with no title left out, as it has no
-- heading. A block's title (a heading below the slide level) is given its
-- level as an attribute, oer-level, which the template reads from the
-- title (heading_levels). A heading inside a quotation, a list, a table,
-- or a figure, which the writer gives as \section and the like inside the
-- frame, where ltx-talk sets nothing and LaTeX's tagging stops on what the
-- template does after a section, is its words in bold, as ltx-talk sets a
-- block's title, in the template's oerheading, which tags them as the
-- heading: a div with the class oer-heading until its footnotes are
-- numbered; one with nothing set in it is no heading, as on the page. Its
-- id stays, for a link to land on. inner: the levels the deck gives the
-- titles of the blocks open.
local function nested_headings(blocks, inner)
  local out = pandoc.Blocks({})
  for _, block in ipairs(blocks) do
    if block.t == 'Div' then
      block.content = nested_headings(block.content, inner)
    elseif block.t == 'Header' then
      if block.level <= LEVEL then
        for i = #inner, 1, -1 do inner[i] = nil end
      else
        while #inner > 0 and inner[#inner] >= block.level do table.remove(inner) end
        if titled(block) then
          block.attributes['oer-level'] = tostring(1 + #inner)
          table.insert(inner, block.level)
        end
      end
    else
      local open = {}
      for i, own in ipairs(inner) do open[i] = own end
      block = block:walk({
        traverse = 'topdown',
        Header = function(header)
          while #open > 0 and open[#open] >= header.level do table.remove(open) end
          -- Its id, which a link may name, kept, as on the page.
          local anchor = pandoc.Span({}, pandoc.Attr(header.identifier))
          if not titled(header) then
            return pandoc.Plain({ anchor, pandoc.Span(header.content) }), false
          end
          local level = 1 + #open
          table.insert(open, header.level)
          return pandoc.Div({ pandoc.Para({ anchor, pandoc.Strong(header.content) }) },
            pandoc.Attr('', { 'oer-heading' }, { level = tostring(level) })), false
        end,
      })
    end
    out:insert(block)
  end
  return out
end

-- The levels nested_headings worked out, where the template reads them,
-- once the footnotes are numbered and the languages marked: a heading in
-- a quotation, a list, or a table in oerheading; a block's title with
-- \oerblocklevel first in it, which the template reads before LaTeX sets
-- the title.
local heading_levels = {
  Div = function(div)
    if not div.classes:includes('oer-heading') then return nil end
    local blocks = pandoc.Blocks({ pandoc.RawBlock('latex',
      ('\\begin{oerheading}[%d]'):format(tonumber(div.attributes.level) or 1)) })
    blocks:extend(div.content)
    blocks:insert(pandoc.RawBlock('latex', '\\end{oerheading}'))
    return blocks
  end,
  Header = function(header)
    local level = tonumber(header.attributes['oer-level'])
    if not level then return nil end
    header.attributes['oer-level'] = nil
    header.content:insert(1, pandoc.RawInline('latex', ('\\oerblocklevel{%d}'):format(level)))
    return header
  end,
}

-- A language tag the PDF can carry: BCP 47's letters, digits, and
-- hyphens, nothing a PDF string would read otherwise.
local function language(attr)
  local lang = attr.attributes.lang
  if lang and lang:match('^%a%a?%a?%a?%a?%a?%a?%a?[%-%w]*$') and not lang:match('%-%-')
      and not lang:match('%-$') then
    return lang
  end
end

local function marked(lang, inlines)
  local out = pandoc.Inlines({ pandoc.RawInline('latex', '\\oerlang{' .. lang .. '}{') })
  out:extend(inlines)
  out:insert(pandoc.RawInline('latex', '}'))
  return out
end

-- A span or a link in another language.
local function inline_language(element)
  local lang = language(element.attr)
  if not lang then return nil end
  element.attributes.lang = nil
  return marked(lang, { element })
end

-- Blocks in another language: each in an oerlanguage environment of its
-- own when they hold a heading, which begins a slide, a section, or a
-- block beamer builds around what follows it, so no environment spans
-- one's end, the heading's words marked; else all in one.
local function in_language(blocks, lang, whole)
  local out = pandoc.Blocks({})
  local opening = pandoc.RawBlock('latex', '\\begin{oerlanguage}{' .. lang .. '}')
  local closing = pandoc.RawBlock('latex', '\\end{oerlanguage}')
  if whole then
    out:insert(opening)
    out:extend(blocks)
    out:insert(closing)
    return out
  end
  for _, block in ipairs(blocks) do
    if block.t == 'Header' then
      if titled(block) then block.content = marked(lang, block.content) end
      out:insert(block)
    elseif block.t == 'Div' and (holds_heading(block, true)
                                 or block.classes:includes('columns')) then
      block.content = in_language(block.content, lang, false)
      out:insert(block)
    else
      out:insert(opening)
      out:insert(block)
      out:insert(closing)
    end
  end
  return out
end

local function div_language(div)
  local lang = language(div.attr)
  if not lang then return nil end
  div.attributes.lang = nil
  local whole = not holds_heading(div, true) and not div.classes:includes('columns')
  div.content = in_language(div.content, lang, whole)
  return div
end

-- A footnote's text given apart from its mark, numbered: its first
-- paragraph set where \footnotetext opens, as the writer sets a
-- footnote's, so the number and the text share a line; in lang, the
-- language of a passage its mark was in, when given. One block, a div, so
-- a passage in another language around it is tagged around all of it.
local function footnote_text(number, content, lang)
  if lang then
    local marked_content = pandoc.Blocks({})
    for i, block in ipairs(content) do
      if i == 1 and (block.t == 'Para' or block.t == 'Plain') then
        block = block:clone()
        block.content = { pandoc.Span(block.content, pandoc.Attr('', {}, { lang = lang })) }
      else
        block = pandoc.Div({ block }, pandoc.Attr('', {}, { lang = lang }))
      end
      marked_content:insert(block)
    end
    content = marked_content
  end
  local opening = pandoc.Inlines({
    pandoc.RawInline('latex', ('\\footnotetext[%d]{\\oerfootnotelabel{%d}'):format(number, number)) })
  local closing = pandoc.RawInline('latex', '}\\stepcounter{footnote}')
  local blocks, rest = pandoc.Blocks({}), 1
  local first = content[1]
  if first and (first.t == 'Para' or first.t == 'Plain') then
    opening:extend(first.content)
    rest = 2
  end
  if rest > #content then
    opening:insert(closing)
    blocks:insert(pandoc.Plain(opening))
    return pandoc.Blocks({ pandoc.Div(blocks) })
  end
  blocks:insert(pandoc.Plain(opening))
  for i = rest, #content do blocks:insert(content[i]) end
  blocks:insert(pandoc.Plain({ closing }))
  return pandoc.Blocks({ pandoc.Div(blocks) })
end

-- Footnotes numbered here, as LaTeX numbers the deck's, in reading order:
-- after, the number of footnotes before. A footnote whose mark the writer
-- would give in a heading, or in a place LaTeX sets twice or after its
-- text, a figure, a table, is given its number here, its mark the
-- template's \oerfootnotemark (mark, the command) and its text given
-- apart (footnote_text); one in an image's description, which the writer
-- leaves out and a figure's image repeats from its caption, isn't
-- counted. A figure's, a table's, or a heading's texts follow it, so a
-- reader meets them after what they're about; a text whose mark is in a
-- passage in another language is in it too (lang).
local function numbering(after)
  local self = { number = after }
  function self.move(element, texts, mark, lang)
    local function passage(inline)
      local own = language(inline.attr)
      if not own then return nil end
      inline.content = self.move(inline.content, texts, mark, own)
      return inline, false
    end
    return element:walk({
      traverse = 'topdown',
      Image = function(image) return image, false end,
      Span = passage,
      Link = passage,
      Note = function(note)
        self.number = self.number + 1
        texts:extend(footnote_text(self.number, note.content, lang))
        return pandoc.RawInline('latex', ('\\%s{%d}'):format(mark or 'oerfootnotemark', self.number))
      end,
    })
  end
  local function texts_after(element)
    local texts = pandoc.Blocks({})
    element = self.move(element, texts)
    if #texts == 0 then return nil end
    texts:insert(1, element)
    return texts, false
  end
  function self.walk(block)
    local walked = pandoc.Blocks({ block }):walk({
      traverse = 'topdown',
      Image = function(image) return image, false end,
      Note = function() self.number = self.number + 1 end,
      Figure = texts_after,
      Table = texts_after,
      Div = function(div)
        if div.classes:includes('oer-heading') then return texts_after(div) end
      end,
    })
    return walked
  end
  return self
end

-- pdf-target.lua, which a section's footnotes, written as LaTeX here,
-- never reach otherwise: a link's /Contents, a formula's repairs.
local PDF_TARGET = pandoc.path.join({ pandoc.path.directory(PANDOC_SCRIPT_FILE),
                                      'pdf-target.lua' })

-- Whether a section's footnotes hold highlighted code (fancyvrb's \VERB),
-- whose macros the writer gives only a deck with highlighted code in it,
-- and the footnotes are written apart from the deck: if so, the deck is
-- given them (slides). A code block in a footnote is already read from a
-- file of its own (footnote-code.lua), the writer highlighting it there.
local highlighted = false

-- A section's footnotes, which the section's slide sets after its
-- heading (the template's \oersectionnotes), as LaTeX, in the language of
-- a div holding the section (lang), passages in other languages tagged,
-- and through pdf-target.lua first: the texts are in the section's title,
-- so a paragraph's end in one is \endgraf, which a title can hold.
local function section_notes(texts, lang)
  if lang then texts = pandoc.Blocks({ pandoc.Div(texts, pandoc.Attr('', {}, { lang = lang })) }) end
  local doc = pandoc.Pandoc(texts):walk({ Span = inline_language, Link = inline_language,
                                         Div = div_language })
  doc = pandoc.utils.run_lua_filter(doc, PDF_TARGET)
  local latex = pandoc.write(doc, 'latex')
  highlighted = highlighted or latex:find('\\VERB', 1, true) ~= nil
  latex = latex:gsub('%s+$', ''):gsub('\n%s*\n+', '\\endgraf\n')
  return pandoc.RawInline('latex', '\\oersectionnotes{' .. latex .. '}')
end

-- Pandoc's highlighting macros, as the writer would give them a deck with
-- highlighted code, for one whose only highlighted code is in a section's
-- footnotes: the template variable, which the writer leaves as it's set,
-- in the colors the writer was given (lib/highlighting.py's theme).
local function highlighting_macros()
  local code = pandoc.Pandoc({ pandoc.Plain({ pandoc.Code('x', pandoc.Attr('', { 'c' })) }) })
  local macros = pandoc.write(code, 'latex',
    { template = pandoc.template.compile('$highlighting-macros$'),
      highlight_method = PANDOC_WRITER_OPTIONS.highlight_method })
  return pandoc.MetaBlocks({ pandoc.RawBlock('latex', macros) })
end

local function heading_text(inlines)
  local text = pandoc.utils.stringify(inlines:walk({ Note = function() return {} end }))
  return (text:gsub('%s+', ' '))
end

local function slides(doc)
  -- A slide's bookmark sits one level below the sections it's in, as
  -- ltx-talk bookmarks \section at level 1 and \subsection at 2.
  local count, open = 0, {}
  local numbers = numbering(0)
  -- lang: the language of the divs around, which a section's footnotes,
  -- set as LaTeX in its title, are given here.
  local function walk(blocks, lang)
    local out = pandoc.Blocks({})
    for _, block in ipairs(blocks) do
      if block.t == 'Header' and block.level < LEVEL then
        while #open > 0 and open[#open] >= block.level do table.remove(open) end
        table.insert(open, block.level)
        local texts = pandoc.Blocks({})
        block.content = numbers.move(block.content, texts, 'oersectionmark')
        if #texts > 0 then block.content:insert(section_notes(texts, lang)) end
        out:insert(block)
      elseif block.t == 'Header' and block.level == LEVEL then
        local text = heading_text(block.content)
        local texts = pandoc.Blocks({})
        block.content = numbers.move(block.content, texts)
        out:insert(block)
        if text:match('%S') then
          count = count + 1
          -- On the frame's first slide only: a frame with pauses is set as
          -- several slides, and each would have the bookmark.
          out:insert(pandoc.RawBlock('latex', ('\\only<1>{\\pdfbookmark[%d]{%s}{oer-slide-%d}}')
            :format(#open + 1, unjoined(tex_escape(text)), count)))
        end
        out:extend(texts)
      elseif block.t == 'Header' then
        -- A block's title: its footnotes' texts at the head of the block.
        local texts = pandoc.Blocks({})
        block.content = numbers.move(block.content, texts)
        out:insert(block)
        out:extend(texts)
      elseif block.t == 'Div' and holds_heading(block, true) then
        block.content = walk(block.content, language(block.attr) or lang)
        out:insert(block)
      else
        out:extend(numbers.walk(block))
      end
    end
    return out
  end
  doc.blocks = walk(doc.blocks)
  if highlighted then doc.meta['highlighting-macros'] = highlighting_macros() end
  return doc
end

return {
  { Div = notes },
  { Pandoc = function(doc) doc.blocks = nested_headings(doc.blocks, {}); return doc end },
  { Pandoc = slides },
  { Span = inline_language, Link = inline_language, Div = div_language },
  heading_levels,
}
