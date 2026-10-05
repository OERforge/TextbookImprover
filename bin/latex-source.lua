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
-- a person can say what it means (latex-macros.tex can).
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

return { { Image = Image, Math = Math } }
