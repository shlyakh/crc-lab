// Dump the one polygon feature class of a file geodatabase through ESRI's File Geodatabase API.
//
//   dump_gdb <path to .gdb> <output prefix>
//
// Writes <prefix>.def.xml (the table definition as the library gives it: fields, spatial
// reference) and <prefix>.rows.bin: per row, little-endian,
//   int32 object id, int16 Flooding_Category, double Shape_Area as stored (NaN if the table has
//   no such field), int32 ESRI shape type, int32 parts, int32 points,
//   int32[parts] index of each part's first point, double[2 * points] x and y as stored,
//   int32 has_z, then double[points] z when has_z is 1.
// Also <prefix>.row<object id>.shape.bin: each row's shape buffer as the library holds it.
// Nothing is altered: no ring is closed, reordered or repaired here.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include <FileGDBAPI.h>

using namespace FileGDBAPI;

static int fail(const char* what, fgdbError hr) {
  std::wstring text;
  ErrorInfo::GetErrorDescription(hr, text);
  std::wcerr << what << L": " << text << L" (" << hr << L")" << std::endl;
  return 1;
}

template <typename T> static void put(std::ofstream& out, const T& value) {
  out.write(reinterpret_cast<const char*>(&value), sizeof(T));
}

int main(int argc, char** argv) {
  if (argc != 3) {
    std::cerr << "usage: dump_gdb <gdb> <output prefix>" << std::endl;
    return 2;
  }
  std::string path(argv[1]), prefix(argv[2]);
  fgdbError hr;
  Geodatabase gdb;
  if ((hr = OpenGeodatabase(std::wstring(path.begin(), path.end()), gdb)) != S_OK)
    return fail("open geodatabase", hr);

  std::vector<std::wstring> names;
  if ((hr = gdb.GetChildDatasets(L"\\", L"Feature Class", names)) != S_OK)
    return fail("list feature classes", hr);
  std::wcout << L"feature classes: " << names.size() << std::endl;
  for (const auto& name : names) std::wcout << L"  " << name << std::endl;
  if (names.size() != 1) {
    std::cerr << "expected exactly one feature class" << std::endl;
    return 3;
  }

  Table table;
  if ((hr = gdb.OpenTable(names[0], table)) != S_OK) return fail("open table", hr);
  std::string definition;
  if ((hr = table.GetDefinition(definition)) != S_OK) return fail("table definition", hr);
  std::ofstream(prefix + ".def.xml", std::ios::binary) << definition;
  int count = 0;
  if ((hr = table.GetRowCount(count)) != S_OK) return fail("row count", hr);
  std::wcout << L"rows by GetRowCount: " << count << std::endl;

  EnumRows rows;
  if ((hr = table.Search(L"*", L"", true, rows)) != S_OK) return fail("search", hr);
  std::ofstream out(prefix + ".rows.bin", std::ios::binary);
  Row row;
  int read = 0;
  while ((hr = rows.Next(row)) == S_OK) {
    int32 oid = 0;
    short code = 0;
    if ((hr = row.GetOID(oid)) != S_OK) return fail("object id", hr);
    if ((hr = row.GetShort(L"Flooding_Category", code)) != S_OK) return fail("category", hr);
    MultiPartShapeBuffer shape;
    if ((hr = row.GetGeometry(shape)) != S_OK) return fail("geometry", hr);
    ShapeType type;
    int parts = 0, points = 0;
    int* part = nullptr;
    Point* xy = nullptr;
    if ((hr = shape.GetShapeType(type)) != S_OK) return fail("shape type", hr);
    if ((hr = shape.GetNumParts(parts)) != S_OK) return fail("parts", hr);
    if ((hr = shape.GetNumPoints(points)) != S_OK) return fail("points", hr);
    if ((hr = shape.GetParts(part)) != S_OK) return fail("part array", hr);
    if ((hr = shape.GetPoints(xy)) != S_OK) return fail("point array", hr);
    put(out, static_cast<int32_t>(oid));
    put(out, static_cast<int16_t>(code));
    // the area ESRI stored with the row: it counts curved segments, which the vertices do not
    double stored_area = std::nan("");
    if (row.GetDouble(L"Shape_Area", stored_area) != S_OK) stored_area = std::nan("");
    put(out, stored_area);
    put(out, static_cast<int32_t>(type));
    put(out, static_cast<int32_t>(parts));
    put(out, static_cast<int32_t>(points));
    out.write(reinterpret_cast<const char*>(part), sizeof(int32_t) * parts);
    for (int i = 0; i < points; ++i) {
      put(out, xy[i].x);
      put(out, xy[i].y);
    }
    double* z = nullptr;
    int32_t has_z = (shape.GetZs(z) == S_OK && z != nullptr) ? 1 : 0;
    put(out, has_z);
    if (has_z) out.write(reinterpret_cast<const char*>(z), sizeof(double) * points);
    // the shape exactly as the library holds it, so that anything beyond plain vertices (curved
    // segments) can be looked at afterwards
    std::ofstream raw(prefix + ".row" + std::to_string(oid) + ".shape.bin", std::ios::binary);
    raw.write(reinterpret_cast<const char*>(shape.shapeBuffer), shape.inUseLength);
    raw.close();
    std::wcout << L"row oid " << oid << L" code " << code << L" shape type " << static_cast<int>(type)
               << L" parts " << parts << L" points " << points << L" z " << has_z
               << L" buffer bytes " << shape.inUseLength << std::endl;
    ++read;
  }
  out.close();
  std::wcout << L"rows read: " << read << L"; last status " << hr << std::endl;
  rows.Close();
  gdb.CloseTable(table);
  CloseGeodatabase(gdb);
  return read == count ? 0 : 4;
}
