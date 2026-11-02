package demo;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;

class OrderService {
    @Autowired
    private OrderRepository repository;

    @Value("${orders.region}")
    private String region;
}
