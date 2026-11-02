package com.example.legacy;

import org.springframework.beans.factory.annotation.Value;

// Frozen legacy module, excluded by the approved policy scope.
public class OldConfig {
    @Value("${legacy.timeout}")
    private int timeout;
}
