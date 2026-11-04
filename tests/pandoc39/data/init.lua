-- Pandoc 3.9's Lua interface, for tests/pandoc39/pandoc, run over the
-- Pandoc installed (3.11 or later): no pandoc.TableBody (3.10 added it);
-- no pandoc.types.Sources (3.9.0.1), nor pandoc.read taking a list of
-- anything but Source objects, which 3.9.0.1 widened to strings and
-- {name, text} tables; PANDOC_VERSION 3.9; and math written as plain text
-- where no html_math_method is given (3.9's default; MathML from 3.11).
pandoc.TableBody = nil
pandoc.types.Sources = nil
PANDOC_VERSION = pandoc.types.Version('3.9')
local read, write, WriterOptions = pandoc.read, pandoc.write, pandoc.WriterOptions
pandoc.read = function(input, ...)
  if type(input) == 'table' then
    for _, item in ipairs(input) do
      if type(item) ~= 'userdata' then
        error('Source expected, got ' .. type(item), 2)
      end
    end
  end
  return read(input, ...)
end
local function plain(opts)
  if opts == nil then return { html_math_method = 'plain' } end
  if type(opts) == 'table' and opts.html_math_method == nil then
    local copy = {}
    for k, v in pairs(opts) do copy[k] = v end
    copy.html_math_method = 'plain'
    return copy
  end
  return opts
end
pandoc.write = function(doc, format, opts) return write(doc, format, plain(opts)) end
pandoc.WriterOptions = function(opts) return WriterOptions(plain(opts)) end
