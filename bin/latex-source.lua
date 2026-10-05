-- latex-source.lua -- when a LaTeX source is read: an image's alt text
-- as LaTeX would give it.
--
-- Pandoc's LaTeX reader (3.12, mkImage in Readers/LaTeX.hs) takes the
-- alt key's value as the raw text of its tokens, and an image without
-- one gets the word "image" (PANDOC-NOTES.md, "The LaTeX reader"). So:
--
-- - "image" is taken as no alt text, which the filter then reports as
--   missing. An author who wrote alt={image} meant no more than that.
-- - alt text holding LaTeX (\%, ~, $...$) is read as LaTeX, so 50\%
--   is 50%.
-- - the marker latexsource.py puts in place of the artifact key makes
--   the image decorative, which is what latex-lab makes it.
--
-- And a formula as texmath, which makes its MathML, can read it. texmath
-- (in Pandoc 3.12) stops on a size command in text inside math
-- (\mbox{\tiny noneg}) and on \rule, and the formula is then written
-- as its TeX. A size changes nothing a screen reader says, and a rule of
-- no width is a strut and one of no height a space, so all three go;
-- a rule that shows is left, since only
-- a person can say what it means (latex-conversion-macros.tex can).
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
local ARTIFACT = 'TextbookImproverArtifact'

function Image(img)
  local alt = stringify(img.caption)
  if alt == ARTIFACT then
    img.caption = {}
    img.classes:insert('decorative')
    return img
  end
  if alt == 'image' or alt == '' then
    img.caption = {}
    return img
  end
  if alt:find('[\\$~{}]') then
    local ok, doc = pcall(pandoc.read, alt, 'latex')
    if ok and #doc.blocks == 1 and doc.blocks[1].content then
      img.caption = doc.blocks[1].content
      return img
    end
  end
  return nil
end

local SIZES = { 'tiny', 'scriptsize', 'footnotesize', 'small',
  'normalsize', 'large', 'Large', 'LARGE', 'huge', 'Huge' }

local OLD_FONTS = { bf = 'textbf', it = 'textit', sf = 'textsf',
  tt = 'texttt', rm = 'textrm', sl = 'textsl', em = 'emph' }

function Math(m)
  local text = m.text
  for _, size in ipairs(SIZES) do
    text = text:gsub('\\' .. size .. '%f[^%a]%s*', '')
  end
  -- A rule of no width is a strut, and one of no height a space, with
  -- or without its optional raise.
  text = text:gsub('\\rule%s*%b[]%s*{%s*0[%a]*%s*}%s*%b{}', '')
  text = text:gsub('\\rule%s*{%s*0[%a]*%s*}%s*%b{}', '')
  text = text:gsub('\\rule%s*%b[]%s*%b{}%s*{%s*0[%a]*%s*}', '\\ ')
  text = text:gsub('\\rule%s*%b{}%s*{%s*0[%a]*%s*}', '\\ ')
  -- A rule no taller than a point and wider than it is tall is a line
  -- to write on, a blank; underlined space says that, and texmath reads it.
  local function blank(width, height)
    local h = tonumber(height)
    if h and h > 0 and h <= 1 then
      return '\\underline{\\hspace{' .. width .. '}}'
    end
    return nil
  end
  text = text:gsub('\\rule%s*%b[]%s*{%s*([%d.]+%a%a)%s*}%s*{%s*([%d.]+)pt%s*}', blank)
  text = text:gsub('\\rule%s*{%s*([%d.]+%a%a)%s*}%s*{%s*([%d.]+)pt%s*}', blank)
  -- A box raised or lowered is the same symbol where texmath is concerned;
  -- \raisebox{1pt}{$\not$} inside an \mbox stops it.
  text = text:gsub('\\raisebox%s*%b{}%s*%b[]%s*%b[]%s*(%b{})', '%1')
  text = text:gsub('\\raisebox%s*%b{}%s*%b[]%s*(%b{})', '%1')
  text = text:gsub('\\raisebox%s*%b{}%s*(%b{})', '%1')
  -- Space inside \mbox is text, which texmath reads as text: an \hspace
  -- there stops it. One at either end goes outside the box, as math
  -- space; one inside is a space.
  text = text:gsub('\\mbox%s*(%b{})', function(arg)
    local inner = arg:sub(2, -2)
    if not inner:find('\\hspace') then return nil end
    local before, after = '', ''
    inner = inner:gsub('^%s*(\\hspace%*?%s*%b{})', function(s) before = s; return '' end)
    inner = inner:gsub('(\\hspace%*?%s*%b{})%s*$', function(s) after = s; return '' end)
    inner = inner:gsub('\\hspace%*?%s*%b{}', ' ')
    return before .. '\\mbox{' .. inner .. '}' .. after
  end)
  -- texmath knows em, pt, in, and cm, not mm; and a length set inside a
  -- formula (\setlength\tabcolsep in an array) lays out nothing a
  -- screen reader says.
  text = text:gsub('(\\hspace%*?%s*{%s*)([%d.]+)%s*mm(%s*})', function(head, n, tail)
    return head .. string.format('%g', tonumber(n) / 10) .. 'cm' .. tail
  end)
  text = text:gsub('\\setlength%s*{?%s*\\%a+%s*}?%s*%b{}', '')
  -- texmath reads \mbox's argument as plain text, so a text command
  -- inside it, \mbox{\textsf R} or \mbox{{\bf c}}, stops it; the
  -- command alone says the same and texmath reads it.
  text = text:gsub('\\mbox%s*{%s*\\(text%a+)%s*(%b{})%s*}', '\\%1%2')
  text = text:gsub('\\mbox%s*{%s*\\(text%a+)%s+([%w])%s*}', '\\%1{%2}')
  for old, new in pairs(OLD_FONTS) do
    text = text:gsub('\\mbox%s*{%s*{%s*\\' .. old .. '%f[^%a]%s*([^{}]*)}%s*}',
      '\\' .. new .. '{%1}')
  end
  if text ~= m.text then
    m.text = text
    return m
  end
  return nil
end

-- A table's header declaration for LaTeX's tagging, which latexsource.py
-- turned into an environment the reader keeps as a div: the pipeline's
-- own declaration, set on the table as a Markdown source's marker sets
-- it (figures-and-tables.lua's data-th-marker), and the div gone.
local DECLARED = { TextbookImproverHeadersFirstRow = 'first-row',
  TextbookImproverHeadersFirstColumn = 'first-column',
  TextbookImproverHeadersBoth = 'both' }

function Div(div)
  -- A table's place in the book's files, which latexsource.py wrapped it
  -- in: kept on the table, for the header pre-pass and a remediated copy.
  local place = div.classes[1] and div.classes[1]:match('^TextbookImproverTable(F%d+N%d+)$')
  if place then
    for _, block in ipairs(div.content) do
      if block.t == 'Table' then
        block.attr.attributes['data-latex-table'] = place
      end
    end
    return div.content
  end
  for _, class in ipairs(div.classes) do
    local declaration = DECLARED[class]
    if declaration then
      for _, block in ipairs(div.content) do
        if block.t == 'Table' then
          block.attr.attributes['data-th-marker'] = declaration
        end
      end
      return div.content
    end
  end
  return nil
end

return { { Image = Image, Math = Math, Div = Div } }
