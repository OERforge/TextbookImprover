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
               description = true, keywords = true, lang = true,
               ['include-before'] = true, ['include-after'] = true }

local function relative(src)
  return not src:match('^%a[%w+.-]*:') and not src:match('^/')
    and not src:match('^#')
end

local function fix_link(link)
  -- link:...[text,title="..."] reads with the title as an attribute; it's
  -- the link's title, where every writer looks for it.
  if link.attributes.title and link.title == '' then
    link.title = link.attributes.title
    link.attributes.title = nil
    return fix_link(link) or link
  end
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

-- A block's layout attributes -- [width=300, float=right] on an image
-- block, a listing, or a table, and a diagram's target= -- arrive as
-- attributes of the block. Pandoc's HTML writer prefixes names it doesn't
-- know with data-, but writes width and target as they are, on <figure>,
-- <pre>, <div>, and <table>, where XHTML allows neither (epubcheck:
-- RSC-005, 43 times in one book's EPUB). A size on a block that holds an
-- image belongs to the image, where it's valid: an attribute when it's a
-- whole number of pixels, a style otherwise. Anywhere else it goes, and
-- so does target, which names a diagram's output file.
-- An alt given as alt="..." is the image's description, which the rest
-- of the pipeline reads from its caption; an empty one says decorative,
-- as in HTML. True when there was one to move.
function alt_to_caption(img, alt)
  if alt == nil then return false end
  if alt == '' then
    if not img.classes:includes('decorative') then img.classes:insert('decorative') end
  elseif #img.caption == 0 then
    local words = pandoc.Inlines({})
    for word in alt:gmatch('%S+') do
      if #words > 0 then words:insert(pandoc.Space()) end
      words:insert(pandoc.Str(word))
    end
    img.caption = words
  end
  return true
end

-- A table written as HTML in a passthrough block (the AsciiDoc target
-- writes a grouped or row-spanned table that way) reaches here as a
-- table, with the header columns Pandoc's HTML reader found. Nothing has
-- declared them, and the main filter keeps only declared ones, so the
-- declaration HTML sources get is made here, by html-source.lua's own
-- handler. A native AsciiDoc table never has any, so it's untouched.
local HERE = PANDOC_SCRIPT_FILE:match('^(.*)[/\\]') or '.'
local html_table
do
  local env = setmetatable({}, { __index = _G })
  assert(loadfile(HERE .. '/html-source.lua', 't', env))()
  html_table = env.Table
end

local function declared(tbl)
  for _, body in ipairs(tbl.bodies) do
    if body.row_head_columns > 0 then return html_table(tbl) or tbl end
  end
  return nil
end

local function layout(el)
  local attrs = el.attributes
  local width, height = attrs.width, attrs.height
  if not (width or height or attrs.target) then return nil end
  attrs.width, attrs.height, attrs.target = nil, nil, nil
  if (width or height) and (el.t == 'Div' or el.t == 'Figure') then
    el = el:walk({
      Image = function(img)
        local style = {}
        for name, value in pairs({ width = width, height = height }) do
          if value and not img.attributes[name] then
            if value:match('^%d+$') then
              img.attributes[name] = value
            else
              style[#style + 1] = name .. ': ' .. value
            end
          end
        end
        if #style > 0 then
          local before = img.attributes.style
          img.attributes.style = (before and before ~= '' and before .. '; '
                                  or '') .. table.concat(style, '; ')
        end
        return img
      end,
    })
  end
  return el
end

function Pandoc(doc)
  local imagesdir = doc.meta.imagesdir
    and pandoc.utils.stringify(doc.meta.imagesdir)
    or os.getenv('ASCIIDOC_IMAGESDIR') or ''
  imagesdir = imagesdir:gsub('/+$', '')
  -- Under a title, "==" is the page's first level below it, so headings
  -- move down one, and by the file's heading-offset besides: the AsciiDoc
  -- target writes one for a page whose headings start at the title's own
  -- level (-1) or skip a level below it (1).
  local titled = doc.meta.title ~= nil
  local offset = tonumber(pandoc.utils.stringify(doc.meta['heading-offset'] or '')) or 0
  for key in pairs(doc.meta) do
    if not KEEP[key] then doc.meta[key] = nil end
  end
  doc = doc:walk({
    Image = function(img)
      local changed = false
      if imagesdir ~= '' and relative(img.src)
          and img.src:sub(1, #imagesdir + 1) ~= imagesdir .. '/' then
        img.src = imagesdir .. '/' .. img.src
        changed = true
      end
      if alt_to_caption(img, img.attributes.alt) then
        img.attributes.alt = nil
        changed = true
      end
      -- image:x.png[link=...] is a linked image, read as an attribute.
      local link = img.attributes.link
      if link then
        img.attributes.link = nil
        return pandoc.Link({ img }, link)
      end
      if changed then return img end
    end,
    Header = function(h)
      if titled then
        h.level = math.max(1, h.level + 1 + offset)
        return h
      end
    end,
    -- Pandoc's reader splits inline code at its spaces: `a b` comes back
    -- as two code elements with a space between. They're one again.
    Inlines = function(inlines)
      local out, changed = pandoc.Inlines({}), false
      for _, el in ipairs(inlines) do
        local n = #out
        if el.t == 'Code' and n >= 2 and out[n].t == 'Space'
            and out[n - 1].t == 'Code' then
          out[n - 1] = pandoc.Code(out[n - 1].text .. ' ' .. el.text,
                                   out[n - 1].attr)
          out:remove(n)
          changed = true
        else
          out:insert(el)
        end
      end
      return changed and out or nil
    end,
    Div = function(div)
      if div.classes:includes('included') then return div.content end
      -- A figure or table with an id comes back from the reader inside a
      -- div marked wrapper=1 that holds the id; the writer drops the div,
      -- so the id goes on the element, where it's written again.
      -- A block image's alt, size, and link arrive on the wrapper too.
      if div.attributes.wrapper and #div.content == 1
          and (div.content[1].t == 'Figure' or div.content[1].t == 'Table') then
        local alt, link = div.attributes.alt, div.attributes.link
        div.attributes.alt, div.attributes.link = nil, nil
        local inner = (layout(div) or div).content[1]
        if div.identifier ~= '' and inner.identifier == '' then
          inner.identifier = div.identifier
        end
        return inner:walk({ Image = function(img)
          alt_to_caption(img, alt)
          if link then return pandoc.Link({ img }, link) end
          return img
        end })
      end
      return layout(div)
    end,
    CodeBlock = layout,
    Table = function(tbl)
      local laid = layout(tbl) or tbl
      return declared(laid) or laid
    end,
    Figure = layout,
    Link = fix_link,
  })
  -- The blocks before and after a page, as the AsciiDoc target writes
  -- them: open blocks named for them, which go back into metadata.
  local kept = pandoc.Blocks({})
  for _, block in ipairs(doc.blocks) do
    local key = block.t == 'Div' and (block.classes:includes('include-before')
      and 'include-before' or block.classes:includes('include-after')
      and 'include-after')
    if key then
      doc.meta[key] = pandoc.MetaBlocks(block.content)
    else
      kept:insert(block)
    end
  end
  doc.blocks = kept
  return doc
end
