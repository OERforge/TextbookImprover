-- target-blocks.lua -- a passage for some editions, and the title block
-- switch. Runs at render time, once per target, with TARGET_NAME set to
-- the target's name and TITLE_BLOCK to "on" or "off".
--
-- A Div or Span with a targets attribute names the targets it is for:
--   ::: {targets="epub print"}   kept for epub and print, dropped elsewhere
--   ::: {targets="!epub"}        kept for every target but epub
-- A kept passage is unwrapped; the attribute never reaches the output.
--
-- A Div or Span with class embed is an <iframe> html-source.lua read,
-- its attributes the frame's and its content a link to what it framed.
-- An HTML writer gets the <iframe> back; every other writer gets the
-- link, since an EPUB reading system can't be relied on to load a remote
-- frame and a printed page can't at all. The Markdown writer is the
-- exception: it keeps the Div, attributes and all, so a Markdown source
-- holds the decision and reads back to it.
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

local TARGET = os.getenv('TARGET_NAME') or ''
local TITLE_BLOCK = (os.getenv('TITLE_BLOCK') or 'on') ~= 'off'

local function wanted(spec)
  -- Names keep; "!name" excludes. A list of only exclusions keeps by
  -- default; a list with any plain name keeps only those.
  local keep, any_plain = nil, false
  for word in spec:gmatch('%S+') do
    if word:sub(1, 1) == '!' then
      if word:sub(2) == TARGET then return false end
    else
      any_plain = true
      if word == TARGET then keep = true end
    end
  end
  if any_plain then return keep == true end
  return true
end

-- An image on another server can't be in an EPUB: the package holds its
-- images, and a reading system won't fetch one (epubcheck: RSC-007). So
-- for an EPUB it's a link to the image, named by its alt text; every
-- other writer keeps the image. The same decision as for a frame.
local function remote_image(img)
  if not FORMAT:match('epub') then return nil end
  if not (img.src:match('^%a[%w+.-]*://') or img.src:match('^//')) then
    return nil
  end
  local text = pandoc.utils.stringify(img.caption)
  if text == '' then
    text = 'Image at ' .. (img.src:match('^%a*:?//([^/?#]+)') or img.src)
  end
  return pandoc.Link(text, img.src)
end

local function escape(value)
  return (value:gsub('&', '&amp;'):gsub('"', '&quot;'):gsub('<', '&lt;'))
end

local function embed(el, block)
  if FORMAT:match('markdown') then return nil end
  if not FORMAT:match('html') or FORMAT:match('epub') then
    return el.content
  end
  local parts = { '<iframe' }
  for _, pair in ipairs(el.attributes) do
    parts[#parts + 1] = (' %s="%s"'):format(pair[1], escape(pair[2]))
  end
  local markup = table.concat(parts) .. '></iframe>'
  if block then return pandoc.RawBlock('html', markup) end
  return pandoc.RawInline('html', markup)
end

local function resolve(el)
  local spec = el.attributes['targets']
  if spec == nil then
    if el.classes:includes('embed') then
      return embed(el, el.t == 'Div')
    end
    return nil
  end
  if not wanted(spec) then return {} end
  return el.content
end

-- A page with no title is named by its own name in <title>, not by
-- the intermediate's file name, which is what Pandoc falls back to
-- ("costs.filtered").
local function own_name()
  local name = (PANDOC_STATE.input_files[1] or ''):match('([^/\\]+)$') or ''
  return (name:gsub('%.json$', ''):gsub('%.filtered$', ''))
end

local function drop_title_block(meta)
  if meta.title == nil and meta.pagetitle == nil and own_name() ~= '' then
    meta.pagetitle = pandoc.MetaString(own_name())
    if TITLE_BLOCK then return meta end
  end
  if TITLE_BLOCK then return meta end
  for _, key in ipairs({ 'subtitle', 'date', 'abstract', 'include-before',
                         'include-after' }) do
    meta[key] = nil
  end
  return meta
end

return {
  { Div = resolve, Span = resolve, Image = remote_image },
  { Meta = drop_title_block },
}
