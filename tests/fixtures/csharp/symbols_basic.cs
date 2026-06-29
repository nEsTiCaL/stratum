using System;
using System.Collections.Generic;

namespace App.Core
{
    public interface IShape
    {
        double Area();
    }

    public class Box : IShape
    {
        private int secret = 1;
        public string Name { get; set; }
        public const int MAX = 10;

        public Box(int id)
        {
            this.Name = "x";
        }

        public double Area()
        {
            return Compute();
        }

        private int Compute()
        {
            return secret;
        }

        private int Compute(int n)
        {
            return n;
        }
    }

    public enum Color { Red, Green }

    static class Util
    {
        public static int Helper() => 1;
    }
}
