#ifndef __cplusplus
#error This file requires a real C++ frontend
#endif

template<class T> class Counter {
public:
    T value;
    T get() const { return value; }
};

template<class T> inline T add(T first, T second) { return first + second; }

class Pair {
public:
    int first, second;
    Pair(int a, int b) : first(a), second(b) {}
    int sum() const { return first + second; }
};

extern "C" int feature_template(int value) {
    Counter<int> counter;
    int &reference = counter.value;
    reference = value;
    return add(counter.get(), 1);
}

extern "C" int feature_constructor(int a, int b) {
    Pair pair(a, b);
    return pair.sum();
}

extern "C" int feature_reference(int *value) {
    int &reference = *value;
    reference += 3;
    return reference;
}
