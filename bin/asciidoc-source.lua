--[[
asciidoc-source.lua

Runs when an AsciiDoc source is read, and does what the reader leaves
undone (Pandoc 3.11's reader, which is the asciidoc library's):

  - A relative image path is joined to the document's imagesdir, which
    the reader keeps as an attribute and doesn't apply: image::hats.png
    with :imagesdir: images names images/hats.png. A chapter that sets
    none takes its master file's, which convert.py passes in
    ASCIIDOC_IMAGESDIR, as Asciidoctor would have.
  - The document's title (= Title) is its metadata, and its sections
    (== Section) come back at level 1. They move down a level, so the
    page has one h1, its title.
  - AsciiDoc's document attributes that steer Asciidoctor's own output
    (toc, icons, stylesheet, sectnums, leveloffset, ...) are dropped
    from the metadata, where Pandoc's templates would read "toc" as a
    switch. What describes the book (title, author, date, description,
    keywords, lang) is kept.
  - A link to an email address gets back the mailto: the reader drops:
    mailto:someone@example.org[Someone] arrives as a link to a file
    called someone@example.org.
  - A link to a scheme and nothing else (a chapter that writes ftp://
    in passing, which the reader takes for a URL) is its text again.
  - An included file's wrapper (a Div with class included, which the
    reader adds around what an include:: brought in) is opened up.

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

local KEEP = { title = true, subtitle = true, author = true, date = true,
               description = true, keywords = true, lang = true }

local function relative(src)
  return not src:match('^%a[%w+.-]*:') and not src:match('^/')
    and not src:match('^#')
end

local function fix_link(link)
  local target = link.target
  if not target:match('^%a[%w+.-]*:') and not target:match('[/#?]')
      and target:match('^[^@%s]+@[^@%s]+%.%a+$') then
    link.target = 'mailto:' .. target
    return link
  end
  if target:match('^%a[%w+.-]*://$') then
    return link.content
  end
  return nil
end

function Pandoc(doc)
  local imagesdir = doc.meta.imagesdir
    and pandoc.utils.stringify(doc.meta.imagesdir)
    or os.getenv('ASCIIDOC_IMAGESDIR') or ''
  imagesdir = imagesdir:gsub('/+$', '')
  local titled = doc.meta.title ~= nil
  for key in pairs(doc.meta) do
    if not KEEP[key] then doc.meta[key] = nil end
  end
  doc = doc:walk({
    Image = function(img)
      if imagesdir ~= '' and relative(img.src)
          and img.src:sub(1, #imagesdir + 1) ~= imagesdir .. '/' then
        img.src = imagesdir .. '/' .. img.src
        return img
      end
    end,
    Header = function(h)
      if titled then
        h.level = h.level + 1
        return h
      end
    end,
    Div = function(div)
      if div.classes:includes('included') then return div.content end
    end,
    Link = fix_link,
  })
  return doc
end
