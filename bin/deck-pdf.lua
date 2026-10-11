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
-- where the writer would mark it for babel, which tags nothing.
--
-- A footnote in a slide's title keeps its mark in the title, and its
-- text goes at the head of the slide (\footnotetext, numbered as LaTeX
-- numbers the deck's footnotes, in order): ltx-talk sets the title after
-- the slide's footnotes, and a footnote there was lost. A footnote in a
-- figure's caption is numbered so too, its text after the figure, since
-- LaTeX sets a caption twice and counted its mark twice.
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

-- A heading inside a quotation, a list, a table, or a figure, which the
-- writer gives as \section and the like inside the frame, where ltx-talk
-- sets nothing and LaTeX's tagging stops on what the template does after
-- a section: its words in bold, as ltx-talk sets a block's title.
local function nested_headings(blocks)
  local out = pandoc.Blocks({})
  for _, block in ipairs(blocks) do
    if block.t == 'Div' then
      block.content = nested_headings(block.content)
    elseif block.t ~= 'Header' then
      block = block:walk({
        Header = function(header)
          return pandoc.Para({ pandoc.Strong(header.content) })
        end,
      })
    end
    out:insert(block)
  end
  return out
end

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
      block.content = marked(lang, block.content)
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
-- footnote's, so the number and the text share a line.
local function footnote_text(number, content)
  local opening = pandoc.Inlines({
    pandoc.RawInline('latex', ('\\footnotetext[%d]{'):format(number)) })
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
    return blocks
  end
  blocks:insert(pandoc.Plain(opening))
  for i = rest, #content do blocks:insert(content[i]) end
  blocks:insert(pandoc.Plain({ closing }))
  return blocks
end

-- Footnotes numbered here, as LaTeX numbers the deck's, in reading order:
-- after, the number of footnotes before. A footnote whose mark the writer
-- would give in a place LaTeX sets twice or after its text, a slide's
-- title, a figure, a table, is given its number here, its mark
-- \oertitlemark and its text given apart (footnote_text); one in an
-- image's description, which the writer leaves out and a figure's image
-- repeats from its caption, isn't counted.
local function numbering(after)
  local self = { number = after }
  function self.move(element, texts)
    return element:walk({
      traverse = 'topdown',
      Image = function(image) return image, false end,
      Note = function(note)
        self.number = self.number + 1
        texts:extend(footnote_text(self.number, note.content))
        return pandoc.RawInline('latex', ('\\oertitlemark{%d}'):format(self.number))
      end,
    })
  end
  function self.walk(block)
    local walked = pandoc.Blocks({ block }):walk({
      traverse = 'topdown',
      Image = function(image) return image, false end,
      Note = function() self.number = self.number + 1 end,
      Figure = function(figure)
        local texts = pandoc.Blocks({})
        figure = self.move(figure, texts)
        if #texts == 0 then return nil end
        texts:insert(figure)
        return texts, false
      end,
      Table = function(table)
        local texts = pandoc.Blocks({})
        table = self.move(table, texts)
        if #texts == 0 then return nil end
        texts:insert(table)
        return texts, false
      end,
    })
    return walked
  end
  return self
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
  local function walk(blocks)
    local out = pandoc.Blocks({})
    for _, block in ipairs(blocks) do
      if block.t == 'Header' and block.level < LEVEL then
        while #open > 0 and open[#open] >= block.level do table.remove(open) end
        table.insert(open, block.level)
        out:extend(numbers.walk(block))
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
            :format(#open + 1, tex_escape(text), count)))
        end
        out:extend(texts)
      elseif block.t == 'Div' and holds_heading(block) then
        block.content = walk(block.content)
        out:insert(block)
      else
        out:extend(numbers.walk(block))
      end
    end
    return out
  end
  doc.blocks = walk(doc.blocks)
  return doc
end

return {
  { Div = notes },
  { Pandoc = function(doc) doc.blocks = nested_headings(doc.blocks); return doc end },
  { Span = inline_language, Link = inline_language, Div = div_language },
  { Pandoc = slides },
}
