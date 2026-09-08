package web

import (
	"context"

	"github.com/sirupsen/logrus"
)

// Usage یک ساختار توخالی است تا ترنسپورت‌ها بدون نیاز به اجرای وب‌پنل کامپایل شوند.
type Usage struct{}

// NewDataStore هیچ وب‌سروری اجرا نمی‌کند و هیچ پورتی باز نخواهد شد.
func NewDataStore(addr string, ctx context.Context, snifferLog string, sniffer bool, statusFunc func() string, logger *logrus.Logger) *Usage {
	return &Usage{}
}

// Monitor هیچ کاری انجام نمی‌دهد (No-Op).
func (u *Usage) Monitor() {}

// AddOrUpdatePort بدون عملیات.
func (u *Usage) AddOrUpdatePort(port int, bytes uint64) {}
