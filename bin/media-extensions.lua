--[[
media-extensions.lua

Renames extracted media to match its real content type, and rewrites the
Image references to match -- entirely inside a single pandoc run.

Word stores images with whatever content type the DOCX declares. OpenStax
files routinely declare application/octet-stream, which pandoc maps to a
".so" extension. Pandoc emits <embed> rather than <img> for an extension it
does not recognize, so a wrong extension produces an image that silently
does not appear.

This replaces a post-hoc rename plus a sed pass over the intermediate: it
operates on pandoc's mediabag before the writer runs, so a reference can
never be left dangling. It requires the conversion to be a single pandoc
invocation -- with a Markdown intermediate, the media is already on disk
and named before the second invocation starts.

Usage:
    pandoc -f docx -t html5 in.docx \
      --lua-filter=media-extensions.lua \
      --extract-media=media -o out.html

Media that cannot be identified is reported to stderr and, when
MEDIA_UNRESOLVED names a file, appended to it as CSV so the calling script
has a list to gate on rather than only a block of trace output. Set
MEDIA_STRICT=1 to abort the run instead of reporting.

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
--]]

local strict = os.getenv('MEDIA_STRICT') == '1'
local report = os.getenv('MEDIA_UNRESOLVED')

local function source_stem()
  local path = (PANDOC_STATE and PANDOC_STATE.input_files
    and PANDOC_STATE.input_files[1]) or ''
  return (path:gsub('.*[/\\]', ''):gsub('%.[^.]+$', ''))
end

-- Commas are replaced rather than quoted: these fields are file names and
-- mime types, which do not contain commas in practice, and a bare
-- replacement keeps the row readable in a terminal.
local function report_unresolved(path, mime, reason)
  if not report then return end
  local fh = io.open(report, 'a')
  if not fh then return end
  local function clean(text)
    return (tostring(text or ''):gsub(',', ';'))
  end
  fh:write(('%s,%s,%s,%s\n'):format(
    clean(path), clean(source_stem()), clean(mime), clean(reason)))
  fh:close()
end

-- Extensions we are willing to emit, keyed by the mime type pandoc reports.
local ext_for_mime = {
  ['image/png']     = '.png',
  ['image/jpeg']    = '.jpg',
  ['image/gif']     = '.gif',
  ['image/svg+xml'] = '.svg',
  ['image/webp']    = '.webp',
  ['image/tiff']    = '.tif',
  ['image/bmp']     = '.bmp',
}

-- When the declared mime is useless (application/octet-stream and friends),
-- fall back to the file signature. These are the formats Word actually
-- stores; anything else is reported rather than guessed at.
local function sniff(data)
  if not data or #data < 12 then return nil end
  if data:sub(1, 8) == '\137PNG\r\n\26\n' then return '.png' end
  if data:sub(1, 3) == '\255\216\255' then return '.jpg' end
  if data:sub(1, 3) == 'GIF' then return '.gif' end
  if data:sub(1, 2) == 'BM' then return '.bmp' end
  if data:sub(1, 4) == 'RIFF' and data:sub(9, 12) == 'WEBP' then return '.webp' end
  if data:sub(1, 4) == 'II*\0' or data:sub(1, 4) == 'MM\0*' then return '.tif' end
  if data:find('<svg', 1, true) then return '.svg' end
  return nil
end

local function has_extension(path, ext)
  return path:lower():sub(-#ext) == ext
end

function Pandoc(doc)
  local renamed, unresolved = {}, 0

  for _, item in ipairs(pandoc.mediabag.list()) do
    local mime, data = pandoc.mediabag.lookup(item.path)
    local ext = ext_for_mime[mime] or sniff(data)

    if not ext then
      unresolved = unresolved + 1
      io.stderr:write(string.format(
        'media-extensions: cannot identify %s (declared %s)\n',
        item.path, mime or 'no mime type'))
      report_unresolved(item.path, mime or 'no mime type',
        'not an image format a browser can display')
    elseif not has_extension(item.path, ext) then
      local newpath = item.path:gsub('%.[%w]+$', '') .. ext
      pandoc.mediabag.insert(newpath, mime, data)
      pandoc.mediabag.delete(item.path)
      renamed[item.path] = newpath
    end
  end

  if unresolved > 0 and strict then
    error(string.format('%d media file(s) could not be identified', unresolved))
  end

  if next(renamed) == nil then return nil end

  return doc:walk {
    Image = function(img)
      local target = renamed[img.src]
      if target then
        img.src = target
        return img
      end
    end
  }
end
