package com.example.orders;

import lombok.Data;

@Data
public class Money {
    private long cents;
    private String currency;
}
