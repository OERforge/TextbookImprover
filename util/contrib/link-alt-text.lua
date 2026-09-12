-- NOT YET WIRED IN. Kept here because it is the working half of roadmap
-- item 2, the bare-URL sidecar: it turns an aria-label attribute on a Link
-- into the /Contents entry of the PDF link annotation. The HTML and EPUB
-- writers already emit that attribute unchanged, so one annotation covers
-- all three outputs.
--
-- Two things are missing before it can be used here: the \LinkAlt and
-- \LinkAltReset macros it calls, which live in a link-alt-preamble.tex
-- that has not been brought across, and a PDF target to use it with.
--
-- link-alt-text.lua
-- Carries {aria-label="..."} on Markdown links through to the PDF as the
-- /Contents entry of the link annotation, which is what Acrobat announces
-- as a link's alternate description.
--
-- Requires the \LinkAlt / \LinkAltReset pair from link-alt-preamble.tex,
-- and a \DocumentMetadata declaration enabling tagging. Without tagging
-- the macros are no-ops and the build still succeeds.

local specials = {
  ['\\'] = '\\textbackslash{}', ['{'] = '\\{', ['}'] = '\\}',
  ['#'] = '\\#', ['$'] = '\\$', ['%'] = '\\%', ['&'] = '\\&',
  ['_'] = '\\_', ['~'] = '\\textasciitilde{}',
  ['^'] = '\\textasciicircum{}'
}

local function tex_escape(s)
  return (s:gsub('[\\{}#%$%%&_~%^]', specials))
end

function Link(el)
  local label = el.attributes['aria-label']
  if not label or not FORMAT:match('latex') then return nil end
  return {
    pandoc.RawInline('latex', '\\LinkAlt{' .. tex_escape(label) .. '}'),
    el,
    pandoc.RawInline('latex', '\\LinkAltReset{}')
  }
end
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
