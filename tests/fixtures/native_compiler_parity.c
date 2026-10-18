/* Original test code, CC0-1.0. No system headers or game assets. */
typedef struct {
    int hp;
    short timer;
    unsigned short flags;
    float x;
    float y;
} NativePlayer;

extern int native_counter;
extern int native_callback(int value);
extern void native_message(const char *text);

int parity_branch(int value, int low, int high) {
    if (value < low) return low;
    if (value > high) return high;
    return value < 0 ? -value : value;
}

int parity_loop(const int *values, int count) {
    int i, result = 0;
    for (i = 0; i < count; i++) {
        if (values[i] & 1) result += values[i] * 3;
        else result -= values[i] >> 1;
    }
    return result;
}

int parity_calls_and_globals(int value) {
    native_counter += native_callback(value);
    native_message("native compiler parity");
    return native_counter;
}

float parity_float(float left, float right) {
    return (left * 1.25f + right) * 0.5f;
}

double parity_double(double left, double right) {
    return left * 0.1 + right / 3.0;
}

long long parity_wide(long long value, unsigned int shift) {
    return ((value << (shift & 31)) ^ (value >> 17)) + 0x123456789LL;
}

int parity_struct(NativePlayer *player, int damage) {
    if (player->timer > 0) return player->hp;
    player->hp -= damage;
    if (player->hp < 0) player->hp = 0;
    player->flags |= 4;
    player->x += player->y * 0.25f;
    player->timer = 60;
    return player->hp;
}

int parity_switch(int value) {
    switch (value) {
        case 0: return native_callback(11);
        case 1: return native_callback(23);
        case 2: return native_callback(37);
        case 3: return native_callback(41);
        case 4: return native_callback(59);
        case 5: return native_callback(61);
        default: return -1;
    }
}
