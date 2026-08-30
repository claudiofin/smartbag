# ⚠️ -Wall -Wextra -Werror on purpose: this is the one part of the project a
# compiler can actually check, so it may as well be strict.
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -O2

test: test_smartbag
	./test_smartbag

test_smartbag: test_smartbag.c smartbag.c smartbag.h
	$(CC) $(CFLAGS) -o $@ test_smartbag.c smartbag.c

clean:
	rm -f test_smartbag

.PHONY: test clean
