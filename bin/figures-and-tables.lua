--[[
  layout-tables-to-figures.lua

  DOCX authors routinely use a borderless one-cell table purely to position
  an image, putting the caption in an ordinary paragraph underneath. Pandoc
  reproduces that faithfully as a <table> with no <th> and no <caption>,
  which fails WCAG 1.3.1 (Info and Relationships): a table element announces
  a data relationship to assistive technology that does not exist here, and
  the caption is not programmatically tied to the image.

  This filter rewrites any table whose entire content is one or more images
  (and no text) into a native Pandoc Figure, which the HTML5 writer emits as
  <figure> / <img> / <figcaption>. Tables containing text are real data
  tables and are left alone.

  - A following "Figure N.N ..." paragraph is absorbed as the caption.
  - The id of the empty anchor span that DOCX cross-references point at is
    moved onto the <figure>, so existing "#fig-00001" links still resolve.
  - Images with no alt text are reported on stderr for manual follow-up.

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

-- Words that introduce a caption, as a comma-separated list. Books differ:
-- OpenStax labels tables "Table 2.1", while other sources label everything
-- "Figure 1.1" including tables, and some use "Exhibit". Set these through
-- the config rather than editing the filter.
local function label_prefixes(name, fallback)
  local list = {}
  for word in (os.getenv(name) or fallback):gmatch('[^,]+') do
    word = word:match('^%s*(.-)%s*$')
    if word ~= '' then list[#list + 1] = word:lower() end
  end
  return list
end

local FIGURE_PREFIXES = label_prefixes('FIGURE_LABEL_PREFIXES', 'Figure')
local TABLE_PREFIXES = label_prefixes('TABLE_LABEL_PREFIXES', 'Table')

-- Collapse runs of whitespace and trim. Declared here because the caption
-- helpers below need it, and a Lua local is only visible after its
-- definition.
local function normalise(text)
  return (text:gsub('%s+', ' '):gsub('^ ', ''):gsub(' $', ''))
end

-- Does the text open with one of these words, on a word boundary? Matching
-- "Table" must not also match "Tables 1 and 2".
local function opens_with(text, prefixes)
  local lower = text:lower()
  for _, prefix in ipairs(prefixes) do
    if lower:sub(1, #prefix) == prefix then
      local next_char = text:sub(#prefix + 1, #prefix + 1)
      if next_char == '' or next_char:match('%W') then
        return prefix
      end
    end
  end
  return nil
end

-- Optional CSV of descriptive captions, one row per table:
--     Table 2.1,"Customer segments by profit, retention, and acquisition"
-- A bare "Table 2.1" is a valid <caption> but describes nothing, and no
-- script can invent the description. Point TABLE_CAPTIONS at a file to
-- merge human-written text in; without it the label is used on its own.
-- Captions are prose and routinely contain commas, so the parser below is
-- a real one: quoted fields, doubled quotes, embedded newlines, CRLF and
-- the UTF-8 BOM that Excel writes are all handled.
local CAPTION_FILE = os.getenv('TABLE_CAPTIONS') or 'table-captions.csv'

-- When TABLE_CAPTIONS_MISSING names a file, every table that ends up with
-- a bare label and no description appends a row to it. The rows are valid
-- CSV in the same shape as CAPTION_FILE, so filling in the description
-- column and appending the file to CAPTION_FILE is the whole workflow.
local MISSING_FILE = os.getenv('TABLE_CAPTIONS_MISSING')

-- The same arrangement for image alt text, keyed on the image path:
--     1-3-.../media/rId26.png,"Marketing environment split into ..."
-- An entry here replaces whatever alt text the DOCX supplied. The path is
-- used as the key because it already contains the per-document media
-- directory, so it stays unique across the whole book.
--
-- Three states, because "no alt text" and "leave the alt text alone" are
-- different decisions:
--     <text>          use this instead of the DOCX alt text
--     <blank>         reviewed, keep whatever the DOCX supplied
--     [decorative]    emit alt="" so assistive technology skips the image
-- A blank cell deliberately does not mean decorative. Leaving the alt
-- attribute off entirely makes screen readers fall back to announcing the
-- file name, which is the noise alt="" exists to suppress, so the
-- decorative case has to be stated rather than inferred from emptiness.
local ALT_FILE = os.getenv('IMAGE_ALT') or 'image-alt.csv'
local ALT_MISSING_FILE = os.getenv('IMAGE_ALT_MISSING')

-- Data tables with no header row are reported here. Unlike the other two
-- reports there is no sidecar to fill in: header text cannot be inferred
-- from the data, and inventing it would be worse than leaving it out. The
-- fix belongs in the DOCX -- mark the header row in Word, or add one where
-- the table genuinely lacks it.
local HEADER_MISSING_FILE = os.getenv('TABLE_HEADERS_MISSING')

-- Accepted spellings of the decorative marker, matched case-insensitively.
local DECORATIVE_MARKERS = {
  ['[decorative]'] = true,
  ['decorative'] = true,
}

-- Alt text is meant to be a short equivalent, not a description of the
-- image at length. Anything past this many characters is reported so it
-- can be shortened, with the long-form detail moved into the surrounding
-- prose where every reader benefits from it. Counted in characters rather
-- than bytes, so accented text is not judged longer than it reads.
local ALT_MAX_CHARS = tonumber(os.getenv('ALT_MAX_CHARS') or '') or 120

local function char_len(text)
  return (utf8 and utf8.len(text)) or #text
end

-- Wrap data tables in a scrollable div. Pandoc's own stylesheet sets
-- `table { display: block; overflow-x: auto }`, and changing a table's
-- display property strips its role from the browser accessibility tree --
-- rows, columns and header associations stop being exposed to screen
-- readers. The companion CSS restores `display: table` and moves the
-- scrolling onto this wrapper instead.
local WRAP_TABLES = true

-- Word stores some equations as pictures whose alt text is MathSpeak, the
-- notation used by maths speech engines. It spells identifiers out letter
-- by letter ("upper C u s t o m e r"), which a general-purpose screen
-- reader reads as individual letters. Rejoining the letters is a purely
-- mechanical undo of that spelling-out -- it does not reinterpret any of
-- the structural words (StartFraction, Over, equals), so it cannot change
-- what the maths says. It is a mitigation, not a fix: the real fix is for
-- these to be real equations in the DOCX rather than images.
local NORMALISE_MATH_ALT = true

-- Word documents often use a tiny transparent GIF as a bullet or spacer.
-- They carry no meaning, they have no alt text, and there can be hundreds
-- of them. SPACER_BELOW is a width ("0.3in", "24px", "0.75cm", "18pt");
-- any image narrower than it is treated as a spacer. STRIP_SPACER decides
-- what happens then: remove the image entirely, or keep it and mark it
-- decorative with alt="". A threshold of 0 disables both, but spacers are
-- still counted and warned about so the setting is discoverable.
local SPACER_BELOW = os.getenv('SPACER_BELOW') or '0'
local STRIP_SPACER = (os.getenv('STRIP_SPACER') or 'false'):lower() == 'true'
local SPACER_LOG = os.getenv('SPACER_LOG')

-- Convert a CSS-ish length to inches. Returns nil if it cannot be read,
-- which matters: an image with no width escapes the spacer rule entirely
-- and is reported rather than silently kept.
local function to_inches(length)
  if length == nil then return nil end
  local number, unit = tostring(length):match('^%s*([%d%.]+)%s*(%a*)%s*$')
  if number == nil then return nil end
  number = tonumber(number)
  if number == nil then return nil end
  unit = unit:lower()
  if unit == '' or unit == 'in' then return number end
  if unit == 'px' then return number / 96 end      -- CSS reference pixel
  if unit == 'pt' then return number / 72 end
  if unit == 'pc' then return number / 6 end
  if unit == 'cm' then return number / 2.54 end
  if unit == 'mm' then return number / 25.4 end
  return nil
end

local SPACER_LIMIT = to_inches(SPACER_BELOW) or 0

-- Used only for the advisory count when the rule is switched off, so that
-- a document full of spacer GIFs still says so rather than silently
-- filling the alt-text report with them.
local SPACER_ADVISORY = 0.3

-- Drop the fixed height DOCX bakes into each image so that the companion
-- CSS (img { max-width: 100%; height: auto }) can scale images down on
-- narrow viewports without distorting them -- WCAG 1.4.10 (Reflow).
-- Set to false to reproduce the DOCX dimensions exactly.
local RESPONSIVE_IMAGES = true

-- Pandoc falls back to the filename for <title> when no title metadata is
-- set, which gives every page a slug like "1-3-factors-comprising-...".
-- Promoting the leading H1 gives a meaningful page title -- WCAG 2.4.2
-- (Page Titled) -- and avoids two competing H1s in the body.
local PROMOTE_H1_TO_TITLE = true

local function warn(msg)
  io.stderr:write('[figures-and-tables] ' .. msg .. '\n')
end

local function is_blank(inline)
  local t = inline.t
  return t == 'Space' or t == 'SoftBreak' or t == 'LineBreak'
    or (t == 'Str' and inline.text:match('^%s*$') ~= nil)
end

-- Walk blocks collecting images and anchor ids.
-- found.extra is set if anything other than images/whitespace turns up.
local function scan_blocks(blocks, found)
  local function scan_inlines(inlines)
    for _, el in ipairs(inlines) do
      if el.t == 'Image' then
        found.images:insert(el)
      elseif el.t == 'Span' then
        if el.identifier ~= '' and #el.content == 0 then
          found.anchor = found.anchor or el.identifier
        end
        scan_inlines(el.content)
      elseif not is_blank(el) then
        found.extra = true
      end
    end
  end

  for _, block in ipairs(blocks) do
    if block.t == 'Para' or block.t == 'Plain' then
      scan_inlines(block.content)
    elseif block.t == 'Div' or block.t == 'BlockQuote' then
      scan_blocks(block.content, found)
    elseif block.t == 'Figure' then
      -- Pandoc's implicit_figures turns a lone image in a cell into a
      -- nested Figure whose caption just repeats the alt text. Unwrap it.
      scan_blocks(block.content, found)
    else
      found.extra = true
    end
  end
end

local function all_rows(tbl)
  local rows = {}
  for _, row in ipairs(tbl.head.rows) do rows[#rows + 1] = row end
  for _, body in ipairs(tbl.bodies) do
    for _, row in ipairs(body.head) do rows[#rows + 1] = row end
    for _, row in ipairs(body.body) do rows[#rows + 1] = row end
  end
  for _, row in ipairs(tbl.foot.rows) do rows[#rows + 1] = row end
  return rows
end

-- Returns (images, anchor) when the table holds nothing but images.
local function image_only_table(tbl)
  local found = { images = pandoc.Inlines({}), anchor = nil, extra = false }
  for _, row in ipairs(all_rows(tbl)) do
    for _, cell in ipairs(row.cells) do
      scan_blocks(cell.contents, found)
      if found.extra then return nil end
    end
  end
  if #found.images == 0 then return nil end
  return found.images, found.anchor
end

-- pandoc.Caption() only exists in newer releases; the plain table form
-- works in every version that has Figure.
local function mk_caption(blocks)
  if pandoc.Caption then return pandoc.Caption(blocks) end
  return { long = pandoc.Blocks(blocks) }
end

local function caption_below(block)
  if block == nil then return nil end
  if block.t ~= 'Para' and block.t ~= 'Plain' then return nil end
  if opens_with(normalise(pandoc.utils.stringify(block.content)),
                FIGURE_PREFIXES) == nil then
    return nil
  end
  return mk_caption({ pandoc.Plain(block.content) })
end

-- MathSpeak font markers, dropped when they precede a spelled-out letter.
local MATH_FONT_WORDS = {
  normal = true, italic = true, bold = true, monospace = true,
  ['double-struck'] = true, script = true, fraktur = true, ['sans-serif'] = true,
}

-- Four or more consecutive single letters is the signature of an
-- identifier that has been spelled out; ordinary alt text never looks
-- like this, so descriptive captions are left alone.
local function looks_spelled_out(text)
  local run = 0
  for token in text:gmatch('%S+') do
    if token:match('^%a$') then
      run = run + 1
      if run >= 4 then return true end
    else
      run = 0
    end
  end
  return false
end

-- Rejoin spelled-out letters into words. "upper"/"lower" mark the case of
-- the next letter and start a new word; everything else passes through
-- untouched.
local function unspell(text)
  local tokens = {}
  for token in text:gmatch('%S+') do tokens[#tokens + 1] = token end

  local out, word = {}, nil
  local function flush()
    if word then out[#out + 1] = word; word = nil end
  end

  local i = 1
  while i <= #tokens do
    local tok, nxt = tokens[i], tokens[i + 1]
    if MATH_FONT_WORDS[tok:lower()] and nxt
      and (nxt:match('^%a$') or nxt == 'upper' or nxt == 'lower') then
      i = i + 1
    elseif (tok == 'upper' or tok == 'lower') and nxt and nxt:match('^%a$') then
      flush()
      word = (tok == 'upper') and nxt:upper() or nxt:lower()
      i = i + 2
    elseif tok:match('^%a$') then
      word = (word or '') .. tok
      i = i + 1
    else
      flush()
      out[#out + 1] = tok
      i = i + 1
    end
  end
  flush()
  return table.concat(out, ' ')
end

-- Turn "Table  2.1  " into inlines, collapsing the stray spaces DOCX
local function text_to_inlines(text)
  local inlines = pandoc.Inlines({})
  for word in text:gmatch('%S+') do
    if #inlines > 0 then inlines:insert(pandoc.Space()) end
    inlines:insert(pandoc.Str(word))
  end
  return inlines
end


-- Minimal RFC 4180 parser. Character-at-a-time rather than line-at-a-time
-- because a quoted field may itself contain a newline.
local function parse_csv(text)
  text = text:gsub('^\239\187\191', '')  -- strip Excel's UTF-8 BOM
  text = text:gsub('\r\n', '\n'):gsub('\r', '\n')

  local rows, row, field, quoted = {}, {}, {}, false
  local i, n = 1, #text

  local function end_field()
    row[#row + 1] = table.concat(field)
    field = {}
  end
  local function end_row()
    end_field()
    if #row > 1 or row[1] ~= '' then rows[#rows + 1] = row end
    row = {}
  end

  while i <= n do
    local c = text:sub(i, i)
    if quoted then
      if c == '"' then
        if text:sub(i + 1, i + 1) == '"' then
          field[#field + 1] = '"'   -- doubled quote is a literal quote
          i = i + 1
        else
          quoted = false
        end
      else
        field[#field + 1] = c
      end
    elseif c == '"' and #field == 0 then
      quoted = true
    elseif c == ',' then
      end_field()
    elseif c == '\n' then
      end_row()
    else
      field[#field + 1] = c
    end
    i = i + 1
  end
  if #field > 0 or #row > 0 then end_row() end

  return rows
end

-- Quote a value for the paste-ready CSV line in the warning below.
local function csv_escape(value)
  if value:find('[",\n]') then
    return '"' .. value:gsub('"', '""') .. '"'
  end
  return value
end

-- A label is "bare" when it is nothing but the word Table and a number.
-- Many DOCX labels already carry their own description ("Table 12.1
-- Pricing Objectives"), and those need no sidecar entry -- the label is
-- the caption. Only bare labels are worth reporting as missing.
--
-- The number is matched as a single token containing at least one digit,
-- so appendix-style "Table A.1" counts as bare while a one-word title
-- like "Table Summary" does not. Erring toward reporting is deliberate:
-- a spurious row costs one blank description to dismiss, whereas a label
-- wrongly judged descriptive would never be reported at all.
local function is_bare_label(label)
  local prefix = opens_with(label, TABLE_PREFIXES)
  if prefix == nil then return false end
  local rest = label:sub(#prefix + 1):match('^%s*(.-)%s*$')
  if rest == nil or rest == '' then return false end
  if rest:find('%s') then return false end
  return rest:find('%d') ~= nil
end

-- Append a CSV row to one of the report files. Handles are opened lazily
-- and kept open for the document; the calling script sorts the rows and
-- adds the header once the whole run finishes.
local handles = {}
local function append_row(path, fields)
  if not path then return end
  local fh = handles[path]
  if fh == false then return end
  if fh == nil then
    fh = io.open(path, 'a')
    if not fh then
      warn('cannot write ' .. path)
      handles[path] = false
      return
    end
    handles[path] = fh
  end
  local escaped = {}
  for i = 1, #fields do escaped[i] = csv_escape(fields[i] or '') end
  fh:write(table.concat(escaped, ',') .. '\n')
end

local function close_handles()
  for path, fh in pairs(handles) do
    if fh then fh:close() end
    handles[path] = nil
  end
end

local function source_document()
  return (PANDOC_STATE and PANDOC_STATE.input_files
    and PANDOC_STATE.input_files[1]) or ''
end

-- First non-empty cell, so a row in the report identifies its table
-- without the reader having to count tables on the page.
local function table_excerpt(tbl)
  local function from_rows(rows)
    for _, row in ipairs(rows) do
      for _, cell in ipairs(row.cells) do
        local text = normalise(pandoc.utils.stringify(cell.contents))
        if text ~= '' then return text end
      end
    end
    return nil
  end

  local text = from_rows(tbl.head.rows)
  if text == nil then
    for _, body in ipairs(tbl.bodies) do
      text = from_rows(body.body) or from_rows(body.head)
      if text then break end
    end
  end
  text = text or ''
  if #text > 60 then text = text:sub(1, 57) .. '...' end
  return text
end

local function record_missing(label, excerpt)
  append_row(MISSING_FILE, { label, '', source_document(), excerpt or '' })
end

local function record_alt(src, reason, current)
  append_row(ALT_MISSING_FILE, { src, '', source_document(), reason, current })
end

-- A table with no label of any kind still needs a key so a caption can be
-- supplied for it. Position is the only thing left to key on: the page it
-- is in, plus which table it is on that page.
--
-- The number must be assigned in reading order, which a Blocks filter
-- cannot do on its own: Pandoc walks nested block lists first, so a table
-- inside a Div or a list item is reached before a table that precedes it
-- in the document. A separate pass runs first and stamps each table with
-- its true position; see the filter list at the end of this file.
local ORDINAL_ATTR = 'data-cc-ordinal'

local function position_key(ordinal)
  local source = source_document():gsub('%.md$', '')
  return source .. '#table-' .. tostring(ordinal)
end


local function record_spacer(src, width, action)
  append_row(SPACER_LOG, { src, source_document(), width, action })
end

local function record_headerless(label, rows, columns)
  append_row(HEADER_MISSING_FILE,
    { label, source_document(), tostring(rows), tostring(columns) })
end

-- Read a sidecar into a key -> value map. A missing file is not an error.
-- Empty values are kept, not dropped: a row with a blank second column
-- means "reviewed, nothing to add", and discarding it here would make it
-- indistinguishable from an absent row so the item would be reported as
-- missing on every subsequent run.
local HEADER_KEYS = { label = true, table = true, image = true, file = true }

local function load_sidecar(path)
  local map = {}
  local fh = path and io.open(path, 'r')
  if not fh then return map end
  local rows = parse_csv(fh:read('a'))
  fh:close()
  for _, row in ipairs(rows) do
    local key = normalise(row[1] or '')
    -- Tolerate header rows anywhere, not just the first line: appending
    -- successive reports carries one along each time.
    if key ~= '' and not HEADER_KEYS[key:lower()] then
      map[key] = normalise(row[2] or '')
    end
  end
  return map
end

local table_descriptions = nil
local function description_for(label)
  if table_descriptions == nil then
    table_descriptions = load_sidecar(CAPTION_FILE)
  end
  -- nil means absent from the file; '' means present but deliberately blank.
  return table_descriptions[label]
end

local image_alts = nil

-- Image alt entries are keyed on the media path with the extension
-- removed. The extension is not stable: step 2 of the conversion script
-- renames each extracted file to match its real content type, so a path
-- recorded as ".../rId57.so" becomes ".../rId57.jpg" once resolved, and a
-- literal key would stop matching the moment that happened -- silently
-- reporting an image as missing alt text that has already been written.
-- The stem is unique within a document's media directory, so nothing is
-- lost by ignoring the extension.
--
-- Deliberately not applied to the table sidecar: those keys are labels
-- like "Table 2.1", where stripping the last dot would give "Table 2".
local function media_stem(path)
  return (path:gsub('%.%w+$', ''))
end

local function alt_for(src)
  if image_alts == nil then
    image_alts = {}
    for key, value in pairs(load_sidecar(ALT_FILE)) do
      local stem = media_stem(key)
      local existing = image_alts[stem]
      if existing ~= nil and existing ~= '' and value ~= '' and existing ~= value then
        warn('conflicting alt text for ' .. stem .. ' in ' .. ALT_FILE
          .. ' -- two rows differing only by extension')
      end
      -- A non-empty value wins over a blank one from a duplicate row.
      if existing == nil or existing == '' then
        image_alts[stem] = value
      end
    end
  end
  return image_alts[media_stem(src)]
end

-- Alt text handling, applied to every image in the document.
--
--   sidecar entry present and non-empty -> use it, replacing whatever the
--     DOCX supplied. Nothing is reported as missing. If that text is over
--     the length limit it is still used, with a note on stderr.
--   sidecar entry marked [decorative] -> emit alt="" and skip all checks.
--   sidecar entry present but blank -> "reviewed, leave it alone".
--   no sidecar entry -> the DOCX alt is used, and the image is reported
--     when that alt is absent or over the length limit.
local spacers_seen = 0
local widthless = 0

function Image(img)
  -- Applies to every image, not just the ones that end up in figures, so
  -- equation images scale on narrow viewports too.
  if RESPONSIVE_IMAGES then img.attributes.height = nil end

  -- Spacer handling runs before anything else: a stripped image should
  -- not also be reported as missing alt text.
  local width = img.attributes.width
  local inches = to_inches(width)

  if inches == nil then
    if SPACER_LIMIT > 0 then
      widthless = widthless + 1
    end
  elseif SPACER_LIMIT > 0 and inches < SPACER_LIMIT then
    spacers_seen = spacers_seen + 1
    if STRIP_SPACER then
      record_spacer(img.src, tostring(width), 'stripped')
      return {}   -- an empty list removes the inline entirely
    end
    record_spacer(img.src, tostring(width), 'decorative')
    img.caption = pandoc.Inlines({})
    img.attributes.alt = ''
    img.attributes.role = 'presentation'
    return img
  elseif SPACER_LIMIT == 0 and inches < SPACER_ADVISORY then
    -- Rule off: count it so the run can point the setting out, but change
    -- nothing and let the image fall through to the usual alt handling.
    spacers_seen = spacers_seen + 1
  end

  local replacement = alt_for(img.src)
  if replacement ~= nil then
    if DECORATIVE_MARKERS[replacement:lower()] then
      -- Clearing the caption alone makes Pandoc omit the attribute
      -- entirely, and a missing alt makes screen readers fall back to
      -- announcing the file name. Setting it explicitly emits alt="".
      --
      -- --embed-resources re-serialises the HTML and rewrites alt="" to a
      -- bare alt. The two are equivalent to an HTML5 parser, but some
      -- assistive technology treats a valueless alt as absent, so
      -- role="presentation" is set as well: it survives that pass intact
      -- and drops the image from the accessibility tree on its own.
      img.caption = pandoc.Inlines({})
      img.attributes.alt = ''
      img.attributes.role = 'presentation'
    elseif replacement ~= '' then
      img.caption = pandoc.Inlines({ pandoc.Str(replacement) })
      local length = char_len(replacement)
      if length > ALT_MAX_CHARS then
        warn(('alt text from %s is %d characters (limit %d): %s')
          :format(ALT_FILE, length, ALT_MAX_CHARS, img.src))
      end
    end
    return img
  end

  local alt = pandoc.utils.stringify(img.caption)
  local is_equation = false

  if NORMALISE_MATH_ALT and alt ~= '' and looks_spelled_out(alt) then
    is_equation = true
    alt = unspell(alt)
    img.caption = pandoc.Inlines({ pandoc.Str(alt) })
    warn('equation image -- alt text was MathSpeak, letters rejoined: '
      .. img.src)
    warn('  consider re-authoring this as a real equation in the DOCX so it '
      .. 'converts to MathML')
  end

  if alt == '' then
    record_alt(img.src, 'missing', '')
    warn('image has no alt text: ' .. img.src)
  else
    local length = char_len(alt)
    if length > ALT_MAX_CHARS then
      local reason = ('too long (%d characters)'):format(length)
      if is_equation then reason = reason .. '; equation image' end
      record_alt(img.src, reason, alt)
      warn(('alt text is %d characters (limit %d): %s')
        :format(length, ALT_MAX_CHARS, img.src))
    end
  end

  return img
end

-- A table has a header row only if the head section holds a row with some
-- text in it. Pandoc gives a table whose DOCX marked no repeating header
-- row an empty head, which is why no <th> is emitted for it at all.
local function has_header_row(tbl)
  for _, row in ipairs(tbl.head.rows) do
    for _, cell in ipairs(row.cells) do
      if pandoc.utils.stringify(cell.contents):match('%S') then return true end
    end
  end
  return false
end

local function table_shape(tbl)
  local rows, columns = 0, #tbl.colspecs
  for _, body in ipairs(tbl.bodies) do
    rows = rows + #body.body + #body.head
  end
  return rows, columns
end

-- Column headers carry scope="col" so the association is explicit rather
-- than inferred from position (WCAG technique H63).
local function mark_column_headers(tbl)
  for _, row in ipairs(tbl.head.rows) do
    for _, cell in ipairs(row.cells) do
      cell.attr.attributes['scope'] = 'col'
    end
  end
end

-- Prose that happens to open with the label word is not a caption.
-- "Table 48. 1 provides and example of how to organize a table..." begins
-- exactly like a label but is the sentence introducing the table, and
-- absorbing it both invents a nonsense caption and deletes the paragraph
-- from the page.
--
-- What separates them is the word after the number. A caption continues
-- with a capital or a separator -- "Table 2.1: Message Transmission
-- Mediums", "Table 18.1 Types of Retailers" -- while a sentence continues
-- with a lowercase verb: "provides", "shows", "lists".
--
-- Length and a closing full stop are deliberately NOT used. Real captions
-- in these books run long and end in a full stop, e.g. "Table 33.1.
-- Presentation Components and Their Functions. Lists the five main parts
-- or components of any presentation (McLean, S., 2003)." Rejecting on
-- those would lose more captions than it saves.
local function looks_like_sentence(text, prefixes)
  local prefix = opens_with(text, prefixes)
  if prefix == nil then return true end

  local rest = text:sub(#prefix + 1):match('^%s*(.-)%s*$') or ''
  -- Drop the number, however the source mangled it ("2.1", "48. 1").
  local tail = rest:gsub('^[%d%.%s]+', '')
  tail = tail:gsub('^[:%-]%s*', '')
  if tail == '' then return false end          -- a bare label is fine

  return tail:sub(1, 1):match('%l') ~= nil
end

local function table_label(block)
  if block == nil then return nil end
  if block.t ~= 'Para' and block.t ~= 'Plain' then return nil end
  local text = normalise(pandoc.utils.stringify(block.content))
  if opens_with(text, TABLE_PREFIXES) == nil then return nil end
  if looks_like_sentence(text, TABLE_PREFIXES) then return nil end
  return text
end

-- A scroll container keeps long tables from forcing the whole page to
-- scroll sideways (WCAG 1.4.10). It is focusable so it can be scrolled by
-- keyboard, and named so the resulting region is not announced anonymously.
local function wrap_table(tbl, label)
  if not WRAP_TABLES then return tbl end
  local attr
  if label then
    attr = pandoc.Attr('', { 'table-wrapper' },
      { tabindex = '0', role = 'region', ['aria-label'] = label })
  else
    attr = pandoc.Attr('', { 'table-wrapper' }, { tabindex = '0' })
  end
  return pandoc.Div({ tbl }, attr)
end

-- A paragraph that is nothing but emphasised text -- Word's usual way of
-- marking a table title. Used to tell a caption sitting above a table
-- from ordinary prose that happens to mention it.
local function is_emphasised_para(block)
  if block == nil then return false end
  if block.t ~= 'Para' and block.t ~= 'Plain' then return false end
  local content = {}
  for _, el in ipairs(block.content) do
    if not is_blank(el) then content[#content + 1] = el end
  end
  if #content ~= 1 then return false end
  return content[1].t == 'Strong' or content[1].t == 'Emph'
end

-- A short emphasised line with no sentence-ending punctuation: the title
-- half of a two-paragraph caption such as "**Table 7.1**" followed by
-- "*Sample Code of Conduct*".
local function is_title_para(block)
  if not is_emphasised_para(block) then return false end
  local text = normalise(pandoc.utils.stringify(block.content))
  if text == '' or #text > 100 then return false end
  if text:match('[%.%?!]$') then return false end
  return true
end

-- Some documents put the caption above the table instead of below, either
-- as one paragraph ("**Table 2.1: Message Transmission Mediums**") or as a
-- bare label followed by a title on the next line ("**Table 7.1**" then
-- "*Sample Code of Conduct*"). Consume whichever shape is there, removing
-- the paragraphs from the body so they are not repeated.
--
-- Anchoring on the label pattern is what keeps this safe: prose that only
-- mentions a table mid-sentence never starts with it, and an unlabelled
-- title is only taken when a labelled paragraph sits directly above it.
local function caption_above(out, has_bare_caption)
  local last = out[#out]
  local prior = out[#out - 1]

  -- Emphasis is deliberately not required here. Captions above a table are
  -- usually bold or italic, but not always: "Table 22.6 Common Formal
  -- Business Report Elements" is plain text in one of these books, and the
  -- sentence test above already excludes the prose this was meant to guard
  -- against.
  local label = table_label(last)
  if label then
    out:remove(#out)
    return label
  end

  if is_title_para(last) then
    local title = normalise(pandoc.utils.stringify(last.content))
    local prior_label = table_label(prior)
    if prior_label and is_emphasised_para(prior) then
      out:remove(#out)
      out:remove(#out)
      return prior_label .. ' ' .. title
    end
    if has_bare_caption then
      out:remove(#out)
      return title
    end
  end

  return nil
end

-- Which side of a table this document puts its captions on, measured in
-- the numbering pass before any caption is claimed. Two adjacent tables
-- with one label between them are genuinely ambiguous -- the label could
-- caption either -- and the only way to resolve it is to look at what the
-- document does everywhere else.
local caption_side = 'unknown'

-- Is the paragraph below this table actually the caption of the *next*
-- one? A document that captions above puts "**Table 7.1**" between two
-- tables, where it belongs to the second. Only meaningful in a document
-- that captions above; where captions sit below, the paragraph after a
-- table is that table's own and must not be given away.
local function belongs_to_next_table(after_next, after_after)
  if after_next == nil then return false end
  if after_next.t == 'Table' then return true end
  if is_title_para(after_next) and after_after ~= nil
    and after_after.t == 'Table' then
    return true
  end
  return false
end

local function caption_data_table(tbl, next_block, after_next, after_after, out)
  local consumed = 0
  local label = nil

  -- Stamped by the numbering pass in reading order; removed here so it
  -- does not reach the HTML.
  local ordinal = tbl.attr.attributes[ORDINAL_ATTR] or '?'
  tbl.attr.attributes[ORDINAL_ATTR] = nil

  if #tbl.caption.long > 0 then
    -- Already captioned: reuse that text to name the scroll region. A
    -- bare label may still have its descriptive title sitting above.
    label = normalise(pandoc.utils.stringify(tbl.caption.long))
    if is_bare_label(label) then
      local extra = caption_above(out, true)
      if extra and extra ~= label and not is_bare_label(extra) then
        -- caption_above may return "Table 7.1 Sample Code of Conduct",
        -- which already carries the label; only join when it does not.
        if extra:sub(1, #label) == label then
          label = extra
        else
          label = label .. ' ' .. extra
        end
        tbl.caption = mk_caption({ pandoc.Plain(text_to_inlines(label)) })
      end
    end
  else
    label = table_label(next_block)
    if label ~= nil and caption_side == 'above'
      and belongs_to_next_table(after_next, after_after) then
      label = nil   -- that paragraph captions the table after this one
    end
    if label == nil then
      local above = caption_above(out, false)
      if above then
        tbl.caption = mk_caption({ pandoc.Plain(text_to_inlines(above)) })
        label = above
      end
    end
    if label then
      consumed = 1
      local inlines = text_to_inlines(label)
      local description = description_for(label)
      if description and description ~= '' then
        inlines:insert(pandoc.Space())
        inlines:extend(text_to_inlines(description))
      elseif description == nil and is_bare_label(label) then
        -- Absent from the sidecar and the label says nothing but a number.
        record_missing(label, table_excerpt(tbl))
        warn('no description for "' .. label .. '"')
      end
      tbl.caption = mk_caption({ pandoc.Plain(inlines) })
    else
      -- No label anywhere. Fall back to the positional key so the table
      -- can still be reported and still be given a caption.
      local key = position_key(ordinal)
      local description = description_for(key)
      if description == nil then
        record_missing(key, table_excerpt(tbl))
        warn('data table has no caption or label: ' .. key)
      elseif description ~= '' then
        label = description
        tbl.caption = mk_caption({ pandoc.Plain(text_to_inlines(label)) })
      end
    end
  end

  if has_header_row(tbl) then
    mark_column_headers(tbl)
  else
    local rows, columns = table_shape(tbl)
    record_headerless(label or '(unlabelled)', rows, columns)
    warn(('data table has no header row: %s (%d rows x %d columns)')
      :format(label or '(unlabelled)', rows, columns))
  end

  return wrap_table(tbl, label), consumed
end

function Blocks(blocks)
  local out = pandoc.Blocks({})
  local i = 1

  while i <= #blocks do
    local block = blocks[i]
    local images, anchor = nil, nil

    if block.t == 'Table' then
      images, anchor = image_only_table(block)
    end

    if images == nil then
      if block.t == 'Table' then
        -- Not a layout table, so it is a real data table: give it a
        -- <caption>, mark its column headers, wrap it for scrolling.
        local wrapped, consumed = caption_data_table(
          block, blocks[i + 1], blocks[i + 2], blocks[i + 3], out)
        out:insert(wrapped)
        i = i + 1 + consumed
      else
        out:insert(block)
        i = i + 1
      end
    else
      -- Caption: the table's own if it has one, else the paragraph below.
      local caption, consumed = nil, 1
      if #block.caption.long > 0 then
        caption = block.caption
      else
        caption = caption_below(blocks[i + 1])
        if caption then consumed = 2 end
      end

      local identifier = anchor
      if identifier == nil or identifier == '' then
        identifier = block.attr.identifier
      end

      local content = pandoc.Inlines({})
      for n, img in ipairs(images) do
        if n > 1 then content:insert(pandoc.Space()) end
        content:insert(img)
      end

      out:insert(pandoc.Figure(
        pandoc.Plain(content),
        caption or mk_caption({}),
        pandoc.Attr(identifier or '', {}, {})
      ))
      i = i + consumed
    end
  end

  return out
end

function Pandoc(doc)
  if SPACER_LIMIT == 0 and spacers_seen > 0 then
    warn(('%d image(s) narrower than %gin look like spacers; set '
      .. 'images.spacer_below in the config to strip or hide them')
      :format(spacers_seen, SPACER_ADVISORY))
  end
  if widthless > 0 then
    warn(('%d image(s) have no readable width, so the spacer rule could '
      .. 'not be applied to them'):format(widthless))
  end
  close_handles()
  if PROMOTE_H1_TO_TITLE
    and doc.meta.title == nil
    and doc.blocks[1] ~= nil
    and doc.blocks[1].t == 'Header'
    and doc.blocks[1].level == 1
  then
    doc.meta.title = pandoc.MetaInlines(doc.blocks[1].content)
    doc.blocks:remove(1)
  end
  return doc
end

-- ---------------------------------------------------------------------------
-- Filter order
--
-- Two passes, because numbering has to happen in reading order and a
-- Blocks filter cannot do that: Pandoc walks nested block lists before the
-- lists that contain them, so a table inside a Div or a list item is
-- visited before a table that precedes it in the document. Numbering there
-- would hand out keys that do not match what the reader sees on the page.
--
-- The first pass walks the document itself, top to bottom, depth first,
-- and stamps each table with its position. The second pass does the real
-- work and strips the stamp before the writer sees it.
-- ---------------------------------------------------------------------------

local function number_tables(blocks, state)
  for index = 1, #blocks do
    local block = blocks[index]
    local kind = block.t

    if kind == 'Table' then
      -- Only data tables are numbered. A table holding nothing but an
      -- image becomes a <figure> later, so counting it here would leave
      -- gaps -- a page with four tables reporting "#table-1, #table-3,
      -- #table-5, #table-6" because five layout tables were counted in
      -- between. The key has to match the tables a reader can see.
      if image_only_table(block) == nil then
        state.n = state.n + 1
        block.attr.attributes[ORDINAL_ATTR] = tostring(state.n)

        -- Tally which side this document captions on. A label directly
        -- below counts as "below"; a label directly above, or a title
        -- line above preceded by a label, counts as "above".
        if table_label(blocks[index + 1]) then
          state.below = state.below + 1
        end
        if table_label(blocks[index - 1]) then
          state.above = state.above + 1
        elseif is_title_para(blocks[index - 1])
          and table_label(blocks[index - 2]) then
          state.above = state.above + 1
        end
      end
      -- A table can itself contain tables; keep walking so those are
      -- numbered after their container rather than being missed.
      for _, row in ipairs(block.head.rows) do
        for _, cell in ipairs(row.cells) do
          number_tables(cell.contents, state)
        end
      end
      for _, body in ipairs(block.bodies) do
        for _, row in ipairs(body.body) do
          for _, cell in ipairs(row.cells) do
            number_tables(cell.contents, state)
          end
        end
      end
    elseif kind == 'Div' or kind == 'BlockQuote' or kind == 'Figure' then
      number_tables(block.content, state)
    elseif kind == 'BulletList' or kind == 'OrderedList' then
      for _, item in ipairs(block.content) do
        number_tables(item, state)
      end
    elseif kind == 'DefinitionList' then
      for _, item in ipairs(block.content) do
        for _, definition in ipairs(item[2]) do
          number_tables(definition, state)
        end
      end
    end
  end
end

return {
  {
    Pandoc = function(doc)
      local state = { n = 0, above = 0, below = 0 }
      number_tables(doc.blocks, state)
      if state.above > state.below then
        caption_side = 'above'
      elseif state.below > 0 then
        caption_side = 'below'
      end
      return doc
    end,
  },
  {
    Image = Image,
    Blocks = Blocks,
    Pandoc = Pandoc,
  },
}
