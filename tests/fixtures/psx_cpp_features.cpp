#ifndef __cplusplus
#error This translation unit requires the original PS1 C++ frontend
#endif

template<class T> class Cell {
public:
    T value;
    Cell(T initial) : value(initial) {}
    T get() const { return value; }
};

int ps1_template(int value) {
    Cell<int> cell(value);
    int &reference = cell.value;
    reference += 3;
    return cell.get();
}

extern int ps1_total;
extern int ps1_callback(int);

int ps1_call(int value) { return ps1_callback(value) + ps1_total; }
float ps1_float(float value) { return (value + 1.25f) * 2.5f; }
const char *ps1_string() { return "PS1 C++"; }

int ps1_table(int index) {
    static const int values[] = {31, 47, 59, 83};
    return values[index & 3];
}

extern "C++" int ps1_overload(int value) { return value * 7; }
extern "C++" int ps1_overload(int *value) { return *value + 11; }
