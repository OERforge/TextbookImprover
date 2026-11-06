-- title-formulas.lua -- each formula of a page's headings as text, by its
-- TeX, for the titles made from a heading outside the filters: a piece's
-- <title> and its entry in the contents (split-pages.py, which names the
-- piece and keys its sidecars by the heading's TeX, as before), and an
-- EPUB chapter's <title> (build-epub.py, which finds the TeX in the
-- formula's MathML, as its annotation). The text is a page's <title>'s and
-- a PDF's bookmark's, x² + y₁, a/b, √x (math-text.lua's title_text), where
-- Pandoc's writers gave such a title the formula's TeX, and the EPUB's
-- its MathML's letters run together (ab for a/b).
--
-- Run at the filter stage last, after math-repair.lua, which can change a
-- formula's TeX, an equation's repairs and \displaystyle before it in
-- running text, a heading's and a page's title heading's too, so that the
-- TeX noted is the one the writers are given (measured: a heading's
-- \overset{–}{X} – µ is \bar{X} - μ after it, in the page's title heading
-- as in its body). target-blocks.lua takes the texts out of a page before
-- a writer sees it.
--
-- A page's own title made from its heading (figures-and-tables.lua marks
-- it title-is-heading) is made again here, of the heading as
-- math-repair.lua leaves it, so that it says what the heading says, where
-- it had been of the formula as the source wrote it: a heading's
-- \overset{–}{X} was X̄ on the page and X^(–) in the page's <title>, the
-- contents, and a cartridge's name for it. The mark goes with it.
--
-- A title the source declares with a formula in it, Markdown's title:
-- The $x^2$ law, has its formulas noted too, for where a title is text: a
-- page's <title> (target-blocks.lua), its entry in the contents and the
-- menu (convert.py), a cartridge's name for it, a Word file's title, and
-- an EPUB's contents page (lib/bookassembly.py), where they had been its
-- TeX ("The x^2 law"). The title keeps its formulas where it's shown.
--
-- A formula math-text.lua can't write, a matrix, is its TeX between
-- dollar signs in those titles too, and each is recorded for the run to
-- say once which formulas are (TITLE_FORMULAS: one formula of a page's a
-- line, as JSON, by the page, since a page is filtered once for each
-- target whose filter settings differ).
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

local mathtext = dofile(pandoc.path.join({ pandoc.path.directory(PANDOC_SCRIPT_FILE),
                                           'math-text.lua' }))

local function note(doc)
  local texts, any, kept, plain = {}, false, {}, {}
  local function each(inlines, declared)
    pandoc.Inlines(inlines):walk({
      Math = function(math_)
        if texts[math_.text] == nil then
          local text, tex = mathtext.title_text(math_)
          texts[math_.text] = pandoc.MetaString(text)
          plain[math_.text] = text
          any = true
          if tex then kept[#kept + 1] = { tex = math_.text, title = declared } end
        end
      end,
    })
  end
  if doc.meta['title-heading'] ~= nil then each(doc.meta['title-heading']) end
  doc.blocks:walk({ Header = function(heading) each(heading.content) end })
  local remade = doc.meta['title-is-heading'] ~= nil
  doc.meta['title-is-heading'] = nil
  if remade and doc.meta['title-heading'] ~= nil then
    doc.meta.title = pandoc.MetaInlines(pandoc.Inlines(doc.meta['title-heading']):walk({
      Math = function(math_) return pandoc.Str(plain[math_.text]) end,
    }))
  elseif pandoc.utils.type(doc.meta.title) == 'Inlines' then
    each(doc.meta.title, true)
  end
  if not any then return remade and doc or nil end
  doc.meta['formula-texts'] = pandoc.MetaMap(texts)
  local found = os.getenv('TITLE_FORMULAS')
  if #kept > 0 and found and found ~= '' then
    local handle = io.open(found, 'a')
    if handle then
      local page = (PANDOC_STATE.input_files[1] or ''):match('([^/\\]+)$') or ''
      for _, row in ipairs(kept) do
        local record = { page = page, tex = row.tex }
        if row.title then record.title = true end
        handle:write(pandoc.json.encode(record) .. '\n')
      end
      handle:close()
    end
  end
  return doc
end

return { { Pandoc = note } }
