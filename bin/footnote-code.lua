-- footnote-code.lua -- a code block in a footnote, for a PDF. Run by
-- build-pdf.py on a book, after target-blocks.lua and before
-- pdf-target.lua, and by convert.py on a deck, before deck-pdf.lua, which
-- moves some footnotes' texts where this would no longer find them.
--
-- LaTeX's footnote reads its text as an argument, and a code block, which
-- the writer writes as a verbatim environment (fancyvrb's Highlighting,
-- or LaTeX's verbatim), can't be read in one: its lines are gone by the
-- time it's set, and LaTeX stopped ("Paragraph ended before
-- \FV@BeginScanning was complete"). fancyvrb's \VerbatimFootnotes, which
-- Pandoc's template gives a book with verbatim in a note, makes
-- \@footnotetext read the text as it goes; LaTeX's tagged footnotes take
-- it as an argument (\footnote {o+m}, latex-lab-footnotes.ltx) and put
-- their own \@footnotetext back as the document begins. So each code
-- block in a footnote is
-- written to a file of its own from the preamble (filecontents*, the
-- block in header-includes, which the writer writes as it would anywhere,
-- highlighting and all, and gives the highlighting macros for), and read
-- where it stood (\OERCodeFile, an \input that a heading's processing and
-- LaTeX's writes leave as it is), so it's read from the file, line by
-- line, when the footnote is set. The files, oer-code-1.tex and on, are
-- written where LaTeX runs, again on each run.
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

local READER = '\\NewDocumentCommand \\OERCodeFile { m } { \\input { #1 } }'

local function Pandoc(doc)
  local files = pandoc.List()
  local function code_block(block)
    local name = ('oer-code-%d.tex'):format(#files + 1)
    files:insert(pandoc.MetaBlocks({
      pandoc.RawBlock('latex', '\\begin{filecontents*}[overwrite]{' .. name .. '}'),
      block,
      pandoc.RawBlock('latex', '\\end{filecontents*}'),
    }))
    return pandoc.RawBlock('latex', '\\OERCodeFile{' .. name .. '}')
  end
  doc.blocks = doc.blocks:walk({
    Note = function(note)
      note.content = note.content:walk({ CodeBlock = code_block })
      return note
    end,
  })
  if #files == 0 then return nil end
  local includes = pandoc.List()
  local given = doc.meta['header-includes']
  if pandoc.utils.type(given) == 'List' then
    includes:extend(given)
  elseif given ~= nil then
    includes:insert(given)
  end
  includes:insert(pandoc.MetaBlocks({ pandoc.RawBlock('latex', READER) }))
  includes:extend(files)
  doc.meta['header-includes'] = includes
  return doc
end

return { { Pandoc = Pandoc } }
