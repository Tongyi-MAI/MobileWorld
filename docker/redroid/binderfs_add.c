#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <linux/android/binderfs.h>

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: %s <binder-control-path> <name> [name2 ...]\n", argv[0]); return 2; }
    int fd = open(argv[1], O_RDONLY | O_CLOEXEC);
    if (fd < 0) { perror("open binder-control"); return 1; }
    int rc = 0;
    for (int i = 2; i < argc; i++) {
        struct binderfs_device device = {0};
        strncpy(device.name, argv[i], sizeof(device.name) - 1);
        if (ioctl(fd, BINDER_CTL_ADD, &device) < 0) {
            if (errno == EEXIST) { fprintf(stderr, "%s: already exists\n", argv[i]); continue; }
            fprintf(stderr, "%s: ioctl failed: %s\n", argv[i], strerror(errno));
            rc = 1;
        } else {
            printf("%s: created major=%u minor=%u\n", argv[i], device.major, device.minor);
        }
    }
    close(fd);
    return rc;
}
