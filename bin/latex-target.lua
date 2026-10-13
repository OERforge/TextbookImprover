-- latex-target.lua -- when a book's LaTeX is written as the latex
-- target: what reading it back as a source needs that the LaTeX doesn't
-- keep. Run by build-pdf.py after footnote-code.lua and pdf-target.lua.
--
-- A code block's language, its first class but its numbering's, which
-- the writer highlights it by and doesn't write, goes in a comment
-- before it, as a Word file's bookmark keeps it (docxtarget's
-- code_language). latexsource.py finds the comment there, before a
-- block in a footnote's file in the preamble too (footnote-code.lua),
-- and latex-source.lua makes it the block's class again. A block's
-- numbering and first number are in the options the writer gives its
-- Highlighting environment, and its id in the label before it.
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

local CODE_MARK = 'TextbookImproverCode'
local NOT_LANGUAGES = { numberLines = true, ['number-lines'] = true,
                        sourceCode = true, numberSource = true }

function CodeBlock(block)
  for _, class in ipairs(block.classes) do
    if not NOT_LANGUAGES[class] then
      return { pandoc.RawBlock('latex', '% ' .. CODE_MARK .. ' ' .. class), block }
    end
  end
  return nil
end
