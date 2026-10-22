
typedef unsigned int size_t;
void *operator new(size_t);
void operator delete(void *);
extern "C" void record_event(int);
class GameObject {
public:
    int value;
    GameObject(int n = 3) : value(n) { record_event(n); }
    virtual ~GameObject();
    virtual int read() const;
};
GameObject::~GameObject() { record_event(-value); }
int GameObject::read() const { return value; }
extern "C" int runtime_heap(int n) {
    GameObject *p = new GameObject(n);
    int result = p->read();
    delete p;
    return result;
}
extern "C" int runtime_static() {
    static GameObject object(7);
    return object.read();
}
extern "C" int runtime_array() {
    GameObject objects[2];
    return objects[0].read() + objects[1].read();
}
