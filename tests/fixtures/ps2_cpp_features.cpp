#ifndef __cplusplus
#error This translation unit requires the original PS2 C++ frontend
#endif

template<class T> class Cell {
public:
    T value;
    Cell(T initial) : value(initial) {}
    T get() const { return value; }
};

int ps2_template(int value) {
    Cell<int> cell(value);
    int &reference = cell.value;
    reference += 3;
    return cell.get();
}

extern int ps2_total;
extern int ps2_callback(int);

int ps2_call(int value) { return ps2_callback(value) + ps2_total; }
float ps2_float(float value) { return (value + 1.25f) * 2.5f; }
const char *ps2_string() { return "PS2 C++"; }

int ps2_table(int index) {
    static const int values[] = {31, 47, 59, 83};
    return values[index & 3];
}

extern "C++" int ps2_overload(int value) { return value * 7; }
extern "C++" int ps2_overload(int *value) { return *value + 11; }
